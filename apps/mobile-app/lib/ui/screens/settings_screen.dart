import 'package:flutter/material.dart';
import '../../core/i18n/app_translations.dart';
import '../../core/theme/app_theme.dart';
import '../../core/sync/sync_manager.dart';

class SettingsScreen extends StatefulWidget {
  final String currentLanguage;
  final ValueChanged<String> onLanguageChanged;

  const SettingsScreen({
    Key? key,
    required this.currentLanguage,
    required this.onLanguageChanged,
  }) : super(key: key);

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final SyncManager _syncManager = SyncManager();
  bool _pushNotifications = true;
  bool _smsAlerts = true;
  bool _offlineMapsDownloaded = true;
  bool _isSyncing = false;

  Future<void> _triggerManualSync() async {
    setState(() => _isSyncing = true);
    final count = await _syncManager.syncPendingReports();
    await _syncManager.fetchAndCacheLatestAlerts();
    setState(() => _isSyncing = false);

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Sync completed. $count reports synced to server.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Language Selection
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Select Language (North East & National)',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: widget.currentLanguage,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  ),
                  items: AppTranslations.languages.entries.map((entry) {
                    return DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value),
                    );
                  }).toList(),
                  onChanged: (lang) {
                    if (lang != null) widget.onLanguageChanged(lang);
                  },
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),

        // Offline Data & Storage
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.download_for_offline, color: AppColors.secondary),
                title: const Text('Offline Risk Maps Package'),
                subtitle: Text(_offlineMapsDownloaded ? 'Downloaded (142 MB) - Ready Offline' : 'Not Downloaded'),
                trailing: TextButton(
                  onPressed: () {
                    setState(() => _offlineMapsDownloaded = !_offlineMapsDownloaded);
                  },
                  child: Text(_offlineMapsDownloaded ? 'Update' : 'Download'),
                ),
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.sync, color: AppColors.primary),
                title: const Text('Sync Offline Data Now'),
                subtitle: const Text('Uploads queued reports and pulls new alerts'),
                trailing: _isSyncing
                    ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                    : IconButton(
                        icon: const Icon(Icons.refresh),
                        onPressed: _triggerManualSync,
                      ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Notifications Preferences
        Card(
          child: Column(
            children: [
              SwitchListTile(
                title: const Text('Emergency Push Alerts'),
                subtitle: const Text('High-priority audio alerts even in Do Not Disturb'),
                value: _pushNotifications,
                onChanged: (v) => setState(() => _pushNotifications = v),
              ),
              const Divider(height: 1),
              SwitchListTile(
                title: const Text('SMS Early Warning Backup'),
                subtitle: const Text('Receive broadcast SMS when data coverage is low'),
                value: _smsAlerts,
                onChanged: (v) => setState(() => _smsAlerts = v),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
