import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../services/mobile_server_service.dart';

enum PairingStep {
  chooseMethod,
  scanningQr,
  submitting,
  waitingApproval,
  success,
  failed,
}

class PairMobileCentralSystemModal extends StatefulWidget {
  final MobileServerService service;
  final VoidCallback? onPaired;

  const PairMobileCentralSystemModal({
    super.key,
    required this.service,
    this.onPaired,
  });

  @override
  State<PairMobileCentralSystemModal> createState() => _PairMobileCentralSystemModalState();
}

class _PairMobileCentralSystemModalState extends State<PairMobileCentralSystemModal>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final TextEditingController _codeController = TextEditingController();
  final TextEditingController _serverController = TextEditingController();
  MobileScannerController? _scannerController;

  PairingStep _step = PairingStep.chooseMethod;
  String? _statusText;
  String? _errorMessage;
  String? _activeSessionId;
  Timer? _pollingTimer;
  int _countdownSeconds = 90;
  Timer? _countdownTimer;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _serverController.text = widget.service.isDirectCloudTunnel
        ? widget.service.cloudTunnelUrl
        : '${widget.service.host}:${widget.service.port}';
    _scannerController = MobileScannerController(
      detectionSpeed: DetectionSpeed.normal,
      facing: CameraFacing.back,
      torchEnabled: false,
    );
  }

  @override
  void dispose() {
    _tabController.dispose();
    _codeController.dispose();
    _serverController.dispose();
    _scannerController?.dispose();
    _pollingTimer?.cancel();
    _countdownTimer?.cancel();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_step != PairingStep.chooseMethod && _step != PairingStep.scanningQr) return;
    final barcodes = capture.barcodes;
    for (final barcode in barcodes) {
      final raw = barcode.rawValue;
      if (raw != null && raw.isNotEmpty) {
        _processQrPayload(raw);
        break;
      }
    }
  }

  Future<void> _processQrPayload(String raw) async {
    final trimmed = raw.trim();
    // Direct 8-digit numeric code scanned
    if (RegExp(r'^\d{8}$').hasMatch(trimmed)) {
      await _executePairing(pairingCode: trimmed);
      return;
    }

    try {
      final json = jsonDecode(trimmed) as Map<String, dynamic>;
      final type = json['type']?.toString().toLowerCase() ?? '';
      if (type.isNotEmpty && !type.contains('pair')) {
        setState(() {
          _errorMessage = 'Invalid QR code. Please scan a SecureLink Central System QR code.';
        });
        return;
      }

      final pairingCode = (json['pairing_code'] ?? json['code'])?.toString() ?? '';
      if (pairingCode.isEmpty) {
        setState(() {
          _errorMessage = 'QR code does not contain a valid pairing code.';
        });
        return;
      }

      final sessionId = (json['session_id'] ?? json['session'])?.toString();
      final serverIp = (json['local_ip'] ?? json['server_ip'])?.toString();
      final serverPort = json['local_port'] is int
          ? json['local_port'] as int
          : (json['server_port'] is int ? json['server_port'] as int : 8080);
      final cloudTunnel = (json['remote_url'] ?? json['cloud_tunnel_url'])?.toString();

      await _executePairing(
        pairingCode: pairingCode,
        sessionId: sessionId,
        serverIp: serverIp,
        serverPort: serverPort,
        cloudTunnelUrl: cloudTunnel,
      );
    } catch (e) {
      setState(() {
        _errorMessage = 'Could not parse QR code data: $e';
      });
    }
  }

  Future<void> _executePairing({
    required String pairingCode,
    String? sessionId,
    String? serverIp,
    int? serverPort,
    String? cloudTunnelUrl,
  }) async {
    setState(() {
      _step = PairingStep.submitting;
      _statusText = 'Submitting pairing request to Central System...';
      _errorMessage = null;
    });

    final res = await widget.service.submitPairingRequest(
      pairingCode: pairingCode,
      sessionId: sessionId,
      serverIp: serverIp,
      serverPort: serverPort,
      cloudTunnelUrl: cloudTunnelUrl,
    );

    if (!mounted) return;

    if (res['status'] == 'pending_approval') {
      _activeSessionId = res['session_id']?.toString() ?? sessionId;
      setState(() {
        _step = PairingStep.waitingApproval;
        _statusText = 'Waiting for administrator approval on Central System...';
        _countdownSeconds = 90;
      });

      _startApprovalPolling(_activeSessionId!);
    } else {
      setState(() {
        _step = PairingStep.failed;
        _errorMessage = res['message'] ?? 'Pairing request failed.';
      });
    }
  }

  void _startApprovalPolling(String sessionId) {
    _pollingTimer?.cancel();
    _countdownTimer?.cancel();

    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      setState(() {
        if (_countdownSeconds > 0) {
          _countdownSeconds--;
        } else {
          _step = PairingStep.failed;
          _errorMessage = 'Pairing session expired. Please generate a new code on the Central System.';
          _pollingTimer?.cancel();
          t.cancel();
        }
      });
    });

    _pollingTimer = Timer.periodic(const Duration(milliseconds: 1500), (t) async {
      if (!mounted) {
        t.cancel();
        return;
      }

      final st = await widget.service.pollPairingStatus(sessionId);
      if (!mounted) return;

      if (st['status'] == 'success' && st['state'] == 'approved') {
        t.cancel();
        _countdownTimer?.cancel();
        setState(() {
          _step = PairingStep.success;
          _statusText = 'Pairing Approved! Mobile Companion Linked Successfully.';
        });
        widget.onPaired?.call();
        Future.delayed(const Duration(milliseconds: 1600), () {
          if (mounted) Navigator.pop(context);
        });
      } else if (st['state'] == 'rejected') {
        t.cancel();
        _countdownTimer?.cancel();
        setState(() {
          _step = PairingStep.failed;
          _errorMessage = 'Pairing request was declined by the administrator.';
        });
      } else if (st['state'] == 'expired') {
        t.cancel();
        _countdownTimer?.cancel();
        setState(() {
          _step = PairingStep.failed;
          _errorMessage = 'Pairing code expired before approval.';
        });
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: MediaQuery.of(context).size.height * 0.85,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header Drag Handle
          Center(
            child: Container(
              width: 38,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.white24,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 14),

          // Modal Title
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF109C6D), Color(0xFF55E2C0)],
                      ),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Icon(Icons.qr_code_scanner_rounded, color: Colors.white, size: 20),
                  ),
                  const SizedBox(width: 12),
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Pair with Central System',
                        style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                      ),
                      Text(
                        'Cross-Network QR & 8-Digit Pairing',
                        style: TextStyle(color: Color(0xFF55E2C0), fontSize: 10.5, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ],
              ),
              IconButton(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close_rounded, color: Colors.white60, size: 20),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Active Step Body
          Expanded(child: _buildStepContent()),
        ],
      ),
    );
  }

  Widget _buildStepContent() {
    switch (_step) {
      case PairingStep.chooseMethod:
      case PairingStep.scanningQr:
        return _buildMethodTabs();
      case PairingStep.submitting:
        return _buildLoadingState('Submitting Pairing Request', _statusText ?? 'Connecting...');
      case PairingStep.waitingApproval:
        return _buildWaitingApprovalState();
      case PairingStep.success:
        return _buildSuccessState();
      case PairingStep.failed:
        return _buildFailedState();
    }
  }

  Widget _buildMethodTabs() {
    return Column(
      children: [
        Container(
          height: 40,
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.05),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
          ),
          child: TabBar(
            controller: _tabController,
            indicator: BoxDecoration(
              color: const Color(0xFF109C6D),
              borderRadius: BorderRadius.circular(10),
            ),
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white60,
            labelStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
            indicatorSize: TabBarIndicatorSize.tab,
            tabs: const [
              Tab(
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.qr_code_scanner_rounded, size: 15),
                    SizedBox(width: 6),
                    Text('Scan QR Code'),
                  ],
                ),
              ),
              Tab(
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.pin_rounded, size: 15),
                    SizedBox(width: 6),
                    Text('Enter 8-Digit Code'),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),

        if (_errorMessage != null) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.red.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.red.withValues(alpha: 0.4)),
            ),
            child: Row(
              children: [
                const Icon(Icons.error_outline_rounded, color: Colors.redAccent, size: 16),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _errorMessage!,
                    style: const TextStyle(color: Colors.redAccent, fontSize: 11),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
        ],

        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              _buildQrScanView(),
              _buildManualCodeView(),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildQrScanView() {
    return Column(
      children: [
        const Text(
          'Point camera at the "Pair Mobile Device" QR code displayed on the Central System Dashboard.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white70, fontSize: 11.5, height: 1.4),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(18),
            child: Stack(
              alignment: Alignment.center,
              children: [
                if (_scannerController != null)
                  MobileScanner(
                    controller: _scannerController!,
                    onDetect: _onDetect,
                    errorBuilder: (context, error) {
                      return Container(
                        color: const Color(0xFF131722),
                        alignment: Alignment.center,
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.videocam_off_rounded, color: Colors.orangeAccent, size: 36),
                            const SizedBox(height: 8),
                            Text(
                              'Camera unavailable: ${error.errorCode.name}',
                              textAlign: TextAlign.center,
                              style: const TextStyle(color: Colors.white70, fontSize: 11),
                            ),
                            const SizedBox(height: 10),
                            TextButton.icon(
                              onPressed: () => _tabController.animateTo(1),
                              icon: const Icon(Icons.pin_rounded, size: 15),
                              label: const Text('Use 8-Digit Code Instead'),
                              style: TextButton.styleFrom(
                                foregroundColor: const Color(0xFF55E2C0),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                // Scanning overlay frame
                Container(
                  width: 220,
                  height: 220,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: const Color(0xFF55E2C0), width: 2.5),
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              tooltip: 'Toggle Flashlight',
              onPressed: () => _scannerController?.toggleTorch(),
              icon: const Icon(Icons.flash_on_rounded, color: Color(0xFF55E2C0), size: 20),
            ),
            IconButton(
              tooltip: 'Switch Camera',
              onPressed: () => _scannerController?.switchCamera(),
              icon: const Icon(Icons.cameraswitch_rounded, color: Color(0xFF55E2C0), size: 20),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildManualCodeView() {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Enter the 8-digit numeric pairing code displayed on the Central System Dashboard.',
            style: TextStyle(color: Colors.white70, fontSize: 11.5, height: 1.4),
          ),
          const SizedBox(height: 16),
          const Text(
            'PAIRING CODE (8 DIGITS):',
            style: TextStyle(color: Color(0xFF55E2C0), fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 0.8),
          ),
          const SizedBox(height: 6),
          TextField(
            controller: _codeController,
            keyboardType: TextInputType.number,
            maxLength: 8,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 24,
              letterSpacing: 6,
              fontWeight: FontWeight.w900,
              fontFamily: 'monospace',
            ),
            textAlign: TextAlign.center,
            decoration: InputDecoration(
              counterText: '',
              hintText: '12345678',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.2)),
              filled: true,
              fillColor: Colors.white.withValues(alpha: 0.05),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.15))),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.15))),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: Color(0xFF55E2C0), width: 1.5)),
            ),
          ),
          const SizedBox(height: 14),

          const Text(
            'CENTRAL SYSTEM HOST OR CLOUDFLARE TUNNEL (OPTIONAL):',
            style: TextStyle(color: Colors.white60, fontSize: 9.5, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          TextField(
            controller: _serverController,
            style: const TextStyle(color: Colors.white, fontSize: 12, fontFamily: 'monospace'),
            decoration: InputDecoration(
              hintText: 'e.g. 10.28.20.11:8080 or *.trycloudflare.com',
              hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.25)),
              filled: true,
              fillColor: Colors.white.withValues(alpha: 0.04),
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1))),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1))),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: Color(0xFF55E2C0))),
            ),
          ),
          const SizedBox(height: 20),

          SizedBox(
            width: double.infinity,
            height: 44,
            child: ElevatedButton.icon(
              onPressed: () {
                final code = _codeController.text.trim();
                if (code.length != 8 || !RegExp(r'^\d{8}$').hasMatch(code)) {
                  setState(() => _errorMessage = 'Please enter an 8-digit numeric code.');
                  return;
                }
                final rawSrv = _serverController.text.trim();
                String? sHost;
                int? sPort;
                String? sTunnel;

                if (rawSrv.contains('trycloudflare.com')) {
                  sTunnel = rawSrv.startsWith('http') ? rawSrv : 'https://$rawSrv';
                } else if (rawSrv.isNotEmpty) {
                  final clean = rawSrv.replaceFirst('http://', '').replaceFirst('https://', '');
                  if (clean.contains(':')) {
                    final parts = clean.split(':');
                    sHost = parts[0];
                    sPort = int.tryParse(parts[1]) ?? 8080;
                  } else {
                    sHost = clean;
                    sPort = 8080;
                  }
                }

                _executePairing(
                  pairingCode: code,
                  serverIp: sHost,
                  serverPort: sPort,
                  cloudTunnelUrl: sTunnel,
                );
              },
              icon: const Icon(Icons.arrow_forward_rounded, size: 16),
              label: const Text('Submit Pairing Request', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF109C6D),
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoadingState(String title, String subtitle) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(
            width: 44,
            height: 44,
            child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFF55E2C0)),
          ),
          const SizedBox(height: 18),
          Text(title, style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text(subtitle, style: const TextStyle(color: Colors.white60, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _buildWaitingApprovalState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Stack(
            alignment: Alignment.center,
            children: [
              SizedBox(
                width: 80,
                height: 80,
                child: CircularProgressIndicator(
                  value: _countdownSeconds / 90.0,
                  strokeWidth: 4,
                  color: const Color(0xFF55E2C0),
                  backgroundColor: Colors.white12,
                ),
              ),
              Text(
                '${_countdownSeconds}s',
                style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w900, fontFamily: 'monospace'),
              ),
            ],
          ),
          const SizedBox(height: 20),
          const Text(
            'Request Submitted!',
            style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              'A prompt has appeared on the Central System Dashboard.\nPlease ask the dashboard administrator to click "Approve".',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white70, fontSize: 11.5, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccessState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 70,
            height: 70,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: const Color(0xFF109C6D).withValues(alpha: 0.2),
              border: Border.all(color: const Color(0xFF55E2C0), width: 2),
            ),
            child: const Icon(Icons.check_rounded, color: Color(0xFF55E2C0), size: 40),
          ),
          const SizedBox(height: 16),
          const Text(
            'Pairing Successful!',
            style: TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text(
            'Authorized and synchronized with Central System.',
            style: TextStyle(color: Colors.white70, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildFailedState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 60,
            height: 60,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.red.withValues(alpha: 0.15),
              border: Border.all(color: Colors.redAccent, width: 2),
            ),
            child: const Icon(Icons.close_rounded, color: Colors.redAccent, size: 34),
          ),
          const SizedBox(height: 16),
          const Text(
            'Pairing Failed',
            style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              _errorMessage ?? 'An error occurred during pairing.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70, fontSize: 11.5, height: 1.4),
            ),
          ),
          const SizedBox(height: 20),
          ElevatedButton(
            onPressed: () {
              setState(() {
                _step = PairingStep.chooseMethod;
                _errorMessage = null;
              });
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF109C6D),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: const Text('Try Again', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }
}
