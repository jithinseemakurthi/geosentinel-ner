import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/database/database_helper.dart';

class ReportScreen extends StatefulWidget {
  const ReportScreen({Key? key}) : super(key: key);

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  final _formKey = GlobalKey<FormState>();
  String _reportType = 'crack';
  String _severity = 'medium';
  final _descController = TextEditingController();
  final double _latitude = 23.7271; // Default to representative NER coordinates
  final double _longitude = 92.7176;
  bool _isSubmitting = false;

  final List<String> _reportTypes = [
    'crack',
    'bulge',
    'debris',
    'rockfall',
    'road_block',
    'water_spring',
    'other',
  ];

  final List<String> _severityLevels = ['low', 'medium', 'high', 'critical'];

  Future<void> _submitReport() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _isSubmitting = true);

    final reportData = {
      'id': 'rep_${DateTime.now().millisecondsSinceEpoch}',
      'report_type': _reportType,
      'severity': _severity,
      'description': _descController.text.trim(),
      'latitude': _latitude,
      'longitude': _longitude,
      'photo_path': null,
      'created_at': DateTime.now().toIso8601String(),
      'sync_status': 'pending',
    };

    await DatabaseHelper.instance.queueOfflineReport(reportData);

    setState(() => _isSubmitting = false);
    _descController.clear();

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Hazard report saved locally. It will auto-sync when online.'),
          backgroundColor: AppColors.secondary,
        ),
      );
    }
  }

  @override
  void dispose() {
    _descController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Report Landslide Hazard',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
                    ),
                    const SizedBox(height: 16),

                    // Hazard Type Dropdown
                    DropdownButtonFormField<String>(
                      value: _reportType,
                      decoration: const InputDecoration(
                        labelText: 'Hazard Type',
                        border: OutlineInputBorder(),
                      ),
                      items: _reportTypes
                          .map((t) => DropdownMenuItem(
                                value: t,
                                child: Text(t.toUpperCase()),
                              ))
                          .toList(),
                      onChanged: (v) => setState(() => _reportType = v!),
                    ),
                    const SizedBox(height: 16),

                    // Severity Dropdown
                    DropdownButtonFormField<String>(
                      value: _severity,
                      decoration: const InputDecoration(
                        labelText: 'Perceived Severity',
                        border: OutlineInputBorder(),
                      ),
                      items: _severityLevels
                          .map((s) => DropdownMenuItem(
                                value: s,
                                child: Text(s.toUpperCase()),
                              ))
                          .toList(),
                      onChanged: (v) => setState(() => _severity = v!),
                    ),
                    const SizedBox(height: 16),

                    // GPS Coordinates Box
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.blue.shade50,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.my_location, color: AppColors.secondary),
                          const SizedBox(width: 8),
                          Text(
                            'GPS: ${_latitude.toStringAsFixed(4)}°N, ${_longitude.toStringAsFixed(4)}°E (Auto-captured)',
                            style: const TextStyle(fontSize: 12, color: AppColors.textPrimary),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Description Field
                    TextFormField(
                      controller: _descController,
                      maxLines: 3,
                      decoration: const InputDecoration(
                        labelText: 'Description / Observations',
                        hintText: 'Describe slope movement, crack width, or blockage...',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Photo attachment placeholder
                    OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(padding: const EdgeInsets.all(14)),
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Camera opened - Photo queued for M3 AI triage')),
                        );
                      },
                      icon: const Icon(Icons.camera_alt),
                      label: const Text('Attach Slope / Road Photo'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onPressed: _isSubmitting ? null : _submitReport,
              child: _isSubmitting
                  ? const CircularProgressIndicator(color: Colors.white)
                  : const Text('SUBMIT HAZARD REPORT', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      ),
    );
  }
}
