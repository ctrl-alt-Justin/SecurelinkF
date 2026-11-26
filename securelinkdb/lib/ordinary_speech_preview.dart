import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'word_error_rate.dart';

const _previewPort = 8081;
const _subscriptionLine = 'securelink-desktop-preview/1\n';
const _entryLimit = 20;

class OrdinarySpeechPreview extends StatefulWidget {
  const OrdinarySpeechPreview({super.key});

  @override
  State<OrdinarySpeechPreview> createState() => _OrdinarySpeechPreviewState();
}

class _OrdinarySpeechPreviewState extends State<OrdinarySpeechPreview> {
  final _entries = ValueNotifier<List<_PreviewEntry>>([]);
  Socket? _socket;
  StreamSubscription<String>? _subscription;
  Timer? _readyTimer;
  bool _enabled = false;
  bool _showing = false;
  int _generation = 0;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      FilterChip(
        label: const Text(
          'Show ordinary speech',
          style: TextStyle(fontSize: 10),
        ),
        selected: _enabled,
        visualDensity: VisualDensity.compact,
        onSelected: _toggle,
      ),
      if (_enabled)
        IconButton(
          tooltip: 'Open speech preview',
          onPressed: _openReview,
          icon: const Icon(Icons.rate_review_outlined, size: 16),
          visualDensity: VisualDensity.compact,
        ),
    ],
  );

  void _toggle(bool enabled) {
    if (!enabled) {
      _disconnect();
      _entries.value = [];
      setState(() => _enabled = false);
      return;
    }
    setState(() => _enabled = true);
    unawaited(_connect(++_generation));
    unawaited(_openReview());
  }

  Future<void> _connect(int generation) async {
    try {
      final socket = await Socket.connect(
        InternetAddress.loopbackIPv4,
        _previewPort,
        timeout: const Duration(seconds: 2),
      );
      if (!mounted || generation != _generation) {
        socket.destroy();
        return;
      }
      _socket = socket;
      var ready = false;
      _readyTimer = Timer(
        const Duration(seconds: 2),
        () => _closed(generation),
      );
      _subscription = utf8.decoder
          .bind(socket)
          .transform(const LineSplitter())
          .listen(
            (line) {
              if (!mounted || generation != _generation) return;
              try {
                final value = jsonDecode(line);
                if (value is! Map<String, dynamic>) return;
                if (!ready) {
                  ready = value['ready'] == true;
                  if (ready) _readyTimer?.cancel();
                  return;
                }
                final transcript = value['transcript'];
                final category = value['category'];
                final score = value['score'];
                if (transcript is! String ||
                    category is! String ||
                    score is! num) {
                  return;
                }
                _entries.value = [
                  _PreviewEntry(transcript, category, score.toDouble()),
                  ..._entries.value.take(_entryLimit - 1),
                ];
              } on FormatException {
                _closed(generation);
              }
            },
            onError: (Object _) => _closed(generation),
            onDone: () => _closed(generation),
          );
      unawaited(
        socket.done.then<void>(
          (_) {},
          onError: (Object _) {
            _closed(generation);
          },
        ),
      );
      socket.write(_subscriptionLine);
    } on SocketException {
      _closed(generation);
    }
  }

  void _closed(int generation) {
    if (!mounted || generation != _generation) return;
    _toggle(false);
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(
      const SnackBar(content: Text('Local speech preview disconnected.')),
    );
  }

  void _disconnect() {
    _generation++;
    _readyTimer?.cancel();
    _readyTimer = null;
    unawaited(_subscription?.cancel());
    _subscription = null;
    _socket?.destroy();
    _socket = null;
  }

  Future<void> _openReview() async {
    if (_showing || !_enabled) return;
    _showing = true;
    try {
      await showDialog<void>(
        context: context,
        builder: (_) => _PreviewDialog(
          entries: _entries,
          onDisable: () {
            if (mounted) _toggle(false);
          },
        ),
      );
    } finally {
      _showing = false;
    }
  }

  @override
  void dispose() {
    _disconnect();
    _entries.dispose();
    super.dispose();
  }
}

class _PreviewEntry {
  _PreviewEntry(this.transcript, this.category, this.severity);

  final String transcript;
  final String category;
  final double severity;
  String reference = '';
  WordErrorRate? wer;
}

class _PreviewDialog extends StatefulWidget {
  const _PreviewDialog({required this.entries, required this.onDisable});

  final ValueNotifier<List<_PreviewEntry>> entries;
  final VoidCallback onDisable;

  @override
  State<_PreviewDialog> createState() => _PreviewDialogState();
}

class _PreviewDialogState extends State<_PreviewDialog> {
  _PreviewEntry? _selected;

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Ordinary speech'),
    content: SizedBox(
      width: 520,
      child: ValueListenableBuilder<List<_PreviewEntry>>(
        valueListenable: widget.entries,
        builder: (context, entries, _) {
          if (entries.isEmpty) {
            _selected = null;
            return const Text('No speech in the preview.');
          }
          final entry = entries.contains(_selected)
              ? _selected!
              : entries.first;
          _selected = entry;
          final wer = entry.wer;
          return SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButton<_PreviewEntry>(
                  isExpanded: true,
                  value: entry,
                  items: [
                    for (final item in entries)
                      DropdownMenuItem(
                        value: item,
                        child: Text(
                          item.transcript,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (item) => setState(() => _selected = item),
                ),
                const SizedBox(height: 12),
                SelectableText(entry.transcript),
                const SizedBox(height: 6),
                Text(
                  '${entry.category} · Severity ${entry.severity.toStringAsFixed(2)}',
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: ObjectKey(entry),
                  initialValue: entry.reference,
                  maxLines: 3,
                  maxLength: 4096,
                  decoration: const InputDecoration(
                    labelText: 'What was actually said',
                  ),
                  onChanged: (value) => setState(() {
                    entry.reference = value;
                    entry.wer = scoreWordErrorRate(value, entry.transcript);
                  }),
                ),
                if (wer == null)
                  const Text('WER unavailable')
                else
                  Text(
                    '${wer.edits} word edits · ${wer.referenceWords} reference words · '
                    '${wer.percentage.toStringAsFixed(1)}% WER',
                  ),
                if (wer?.needsReview ?? false)
                  const Chip(label: Text('Needs transcript review')),
              ],
            ),
          );
        },
      ),
    ),
    actions: [
      TextButton(
        onPressed: () {
          widget.onDisable();
          Navigator.of(context).pop();
        },
        child: const Text('Turn off preview'),
      ),
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text('Close'),
      ),
    ],
  );
}
