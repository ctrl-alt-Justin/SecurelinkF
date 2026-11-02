import 'package:flutter/material.dart';
import 'package:audioplayers/audioplayers.dart';
import '../services/mobile_server_service.dart';
import '../widgets/mobile_components.dart';

class IncidentsScreen extends StatefulWidget {
  final MobileServerService service;

  const IncidentsScreen({super.key, required this.service});

  @override
  State<IncidentsScreen> createState() => _IncidentsScreenState();
}

class _IncidentsScreenState extends State<IncidentsScreen> {
  bool _filterImportantOnly = true;
  String _searchQuery = '';
  final AudioPlayer _audioPlayer = AudioPlayer();
  String? _currentlyPlayingId;
  PlayerState _playerState = PlayerState.stopped;

  @override
  void initState() {
    super.initState();
    _audioPlayer.onPlayerStateChanged.listen((state) {
      if (mounted) setState(() => _playerState = state);
    });
  }

  @override
  void dispose() {
    _audioPlayer.stop();
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _toggleAudio(String incidentId, String? audioUrl) async {
    if (audioUrl == null || audioUrl.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Audio evidence not available on server.'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }

    // Resolve URL to current live server endpoint (Cloudflare tunnel or LAN host)
    String resolvedUrl = audioUrl;
    final baseHttp = widget.service.baseHttpUrl;
    if (resolvedUrl.contains('127.0.0.1') || resolvedUrl.contains('localhost')) {
      final path = resolvedUrl.replaceFirst(RegExp(r'https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?'), '');
      resolvedUrl = '$baseHttp$path';
    } else if (resolvedUrl.startsWith('/')) {
      resolvedUrl = '$baseHttp$resolvedUrl';
    } else if (!resolvedUrl.startsWith('http://') && !resolvedUrl.startsWith('https://')) {
      resolvedUrl = '$baseHttp/recordings/audio/$resolvedUrl';
    }

    if (_currentlyPlayingId == incidentId && _playerState == PlayerState.playing) {
      await _audioPlayer.pause();
    } else {
      setState(() => _currentlyPlayingId = incidentId);
      try {
        await _audioPlayer.stop();
        await _audioPlayer.play(UrlSource(resolvedUrl));
      } catch (e) {
        if (mounted) {
          setState(() => _currentlyPlayingId = null);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Error playing audio: $e')),
          );
        }
      }
    }
  }

  List<IncidentReport> get _filteredIncidents {
    final pool = _filterImportantOnly
        ? widget.service.importantIncidents
        : widget.service.allIncidents;

    if (_searchQuery.trim().isEmpty) return pool;
    final q = _searchQuery.toLowerCase();
    return pool.where((i) {
      final alias = widget.service.getPinAlias(i.deviceId)?.toLowerCase() ?? '';
      return i.deviceId.toLowerCase().contains(q) ||
          i.transcript.toLowerCase().contains(q) ||
          i.threatLabel.toLowerCase().contains(q) ||
          alias.contains(q);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final incidents = _filteredIncidents;
    final totalImportant = widget.service.importantIncidents.length;
    final totalEvents = widget.service.allIncidents.length;

    return RefreshIndicator(
      color: MobileDesignSystem.primaryGreen,
      backgroundColor: const Color(0xFF0C131A),
      onRefresh: () async {
        widget.service.reconnect();
      },
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        children: [
          // Telemetry Hero Header
          MobileGlassCard(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(7),
                          decoration: BoxDecoration(
                            color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.16),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.shield_outlined,
                            color: MobileDesignSystem.primaryGreenMint,
                            size: 18,
                          ),
                        ),
                        const SizedBox(width: 8),
                        const Text(
                          'Safety Incidents Feed',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 15,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: widget.service.isConnected
                            ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.16)
                            : Colors.white.withValues(alpha: 0.06),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: widget.service.isConnected
                              ? MobileDesignSystem.primaryGreen.withValues(alpha: 0.35)
                              : Colors.white12,
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 6,
                            height: 6,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: widget.service.isConnected
                                  ? MobileDesignSystem.primaryGreen
                                  : Colors.white54,
                            ),
                          ),
                          const SizedBox(width: 5),
                          Text(
                            widget.service.isConnected ? 'LIVE STREAM' : 'OFFLINE',
                            style: TextStyle(
                              color: widget.service.isConnected
                                  ? MobileDesignSystem.primaryGreenMint
                                  : Colors.white54,
                              fontSize: 9.5,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Metrics Row
                Row(
                  children: [
                    Expanded(
                      child: _metricBox(
                        title: 'Flagged Words',
                        value: '$totalImportant',
                        color: totalImportant > 0
                            ? MobileDesignSystem.statusThreat
                            : MobileDesignSystem.primaryGreenMint,
                        icon: Icons.warning_amber_rounded,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _metricBox(
                        title: 'Total Transcripts',
                        value: '$totalEvents',
                        color: Colors.white70,
                        icon: Icons.receipt_long_rounded,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: _metricBox(
                        title: 'Fleet Status',
                        value: widget.service.onlineCount > 0 ? 'ARMED' : 'STANDBY',
                        color: widget.service.onlineCount > 0
                            ? MobileDesignSystem.primaryGreen
                            : Colors.white38,
                        icon: Icons.sensors_rounded,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Filter & Search Controls
          Row(
            children: [
              Expanded(
                child: Container(
                  height: 42,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.04),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                  ),
                  child: TextField(
                    onChanged: (val) => setState(() => _searchQuery = val),
                    style: const TextStyle(color: Colors.white, fontSize: 13),
                    decoration: InputDecoration(
                      hintText: 'Search words or pin ID...',
                      hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 12.5),
                      prefixIcon: Icon(Icons.search_rounded, size: 18, color: Colors.white.withValues(alpha: 0.45)),
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // Filter Toggle Button
              GestureDetector(
                onTap: () => setState(() => _filterImportantOnly = !_filterImportantOnly),
                child: Container(
                  height: 42,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  decoration: BoxDecoration(
                    color: _filterImportantOnly
                        ? MobileDesignSystem.statusThreat.withValues(alpha: 0.16)
                        : Colors.white.withValues(alpha: 0.06),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: _filterImportantOnly
                          ? MobileDesignSystem.statusThreat.withValues(alpha: 0.45)
                          : Colors.white12,
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        _filterImportantOnly ? Icons.filter_alt_rounded : Icons.filter_alt_off_rounded,
                        size: 16,
                        color: _filterImportantOnly
                            ? MobileDesignSystem.statusThreat
                            : Colors.white60,
                      ),
                      const SizedBox(width: 5),
                      Text(
                        _filterImportantOnly ? 'Important' : 'All',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: _filterImportantOnly
                              ? MobileDesignSystem.statusThreat
                              : Colors.white60,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Incidents List or Empty Placeholder
          if (incidents.isEmpty)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
              alignment: Alignment.center,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.10),
                      border: Border.all(color: MobileDesignSystem.primaryGreen.withValues(alpha: 0.25)),
                    ),
                    child: const Icon(Icons.verified_user_rounded, color: MobileDesignSystem.primaryGreenMint, size: 32),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Campus Sentinel Clear',
                    style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _filterImportantOnly
                        ? 'No verbal harassment, swear words, or threats detected in current monitoring session.'
                        : 'No audio transcripts recorded yet. Speak into your pin to test.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 12, height: 1.4),
                  ),
                ],
              ),
            )
          else
            ListView.separated(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: incidents.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (ctx, index) {
                final inc = incidents[index];
                return _buildIncidentCard(inc);
              },
            ),
        ],
      ),
    );
  }

  Widget _metricBox({
    required String title,
    required String value,
    required Color color,
    required IconData icon,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.03),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 12, color: color),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 9.5),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }

  Widget _buildIncidentCard(IncidentReport inc) {
    final alias = widget.service.getPinAlias(inc.deviceId);
    final isPlaying = _currentlyPlayingId == inc.id && _playerState == PlayerState.playing;

    Color badgeColor = MobileDesignSystem.primaryGreenMint;
    String gradeLabel = 'CLEAR';
    if (inc.isDanger) {
      badgeColor = MobileDesignSystem.statusDanger;
      gradeLabel = 'DANGER';
    } else if (inc.isThreat) {
      badgeColor = MobileDesignSystem.statusThreat;
      gradeLabel = 'THREAT';
    } else if (inc.isFlagged) {
      badgeColor = MobileDesignSystem.statusWarning;
      gradeLabel = 'WARNING';
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: badgeColor.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: badgeColor.withValues(alpha: 0.35),
          width: 1.0,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.25),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header Row
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: badgeColor.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(7),
                  border: Border.all(color: badgeColor.withValues(alpha: 0.45), width: 0.8),
                ),
                child: Text(
                  '$gradeLabel (${inc.threatScore.toStringAsFixed(1)}/10)',
                  style: TextStyle(color: badgeColor, fontSize: 10.5, fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      alias != null ? '$alias (${inc.deviceId})' : inc.deviceId,
                      style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      inc.threatLabel,
                      style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10),
                    ),
                  ],
                ),
              ),
              Text(
                inc.timestamp.contains(' ') ? inc.timestamp.split(' ').last : inc.timestamp,
                style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 10),
              ),
            ],
          ),
          const SizedBox(height: 10),

          // Highlighted Transcript
          MobileThreatTranscript(
            text: inc.transcript,
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
          ),
          const SizedBox(height: 12),

          // Camera Snapshot for DANGER Incidents
          if (inc.isDanger) ...[
            Container(
              height: 120,
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.35),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFFF4D67).withValues(alpha: 0.3)),
              ),
              child: Stack(
                children: [
                  if (inc.snapshotUrl != null && inc.snapshotUrl!.isNotEmpty)
                    Positioned.fill(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(11),
                        child: Image.network(
                          inc.snapshotUrl!,
                          fit: BoxFit.cover,
                          loadingBuilder: (context, child, loadingProgress) {
                            if (loadingProgress == null) return child;
                            return const Center(
                              child: CircularProgressIndicator(
                                color: Color(0xFFFF4D67),
                                strokeWidth: 2,
                              ),
                            );
                          },
                          errorBuilder: (context, error, stackTrace) {
                            return Center(
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Icon(Icons.videocam_rounded, size: 28, color: const Color(0xFFFF4D67).withValues(alpha: 0.7)),
                                  const SizedBox(height: 4),
                                  const Text('DANGER SNAPSHOT PENDING', style: TextStyle(color: Colors.white70, fontSize: 9.5, fontWeight: FontWeight.w600)),
                                ],
                              ),
                            );
                          },
                        ),
                      ),
                    )
                  else
                    Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.videocam_rounded, size: 28, color: const Color(0xFFFF4D67).withValues(alpha: 0.7)),
                          const SizedBox(height: 4),
                          const Text('OV2640 DANGER SNAPSHOT CAPTURED', style: TextStyle(color: Colors.white70, fontSize: 9.5, fontWeight: FontWeight.w600)),
                          const SizedBox(height: 2),
                          Text('Triggered automatically by DANGER grade speech', style: TextStyle(color: Colors.white.withValues(alpha: 0.3), fontSize: 7.5)),
                        ],
                      ),
                    ),
                  Positioned(
                    top: 6,
                    left: 8,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFF4D67).withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: const Color(0xFFFF4D67).withValues(alpha: 0.4)),
                      ),
                      child: Text(
                        inc.snapshotUrl != null && inc.snapshotUrl!.isNotEmpty ? 'SNAPSHOT • ${inc.deviceId}' : 'REC • ${inc.deviceId}',
                        style: const TextStyle(fontSize: 7.5, color: Color(0xFFFF4D67), fontWeight: FontWeight.w700),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],

          // Audio & Forensic Footer
          Row(
            children: [
              if (inc.audioUrl != null && inc.audioUrl!.isNotEmpty) ...[
                GestureDetector(
                  onTap: () => _toggleAudio(inc.id, inc.audioUrl),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: isPlaying
                          ? MobileDesignSystem.primaryGreen
                          : Colors.white.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: isPlaying
                            ? MobileDesignSystem.primaryGreenMint
                            : Colors.white12,
                      ),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                          size: 15,
                          color: isPlaying ? Colors.white : MobileDesignSystem.primaryGreenMint,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          isPlaying ? 'Playing Audio...' : 'Audio Evidence',
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w700,
                            color: isPlaying ? Colors.white : Colors.white70,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(width: 8),
              ],
              const Spacer(),
              Text(
                'AI TagalogBERT Verified',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 9.5),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
