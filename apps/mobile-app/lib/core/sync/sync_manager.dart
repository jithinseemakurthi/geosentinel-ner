import 'dart:async';
import '../database/database_helper.dart';
import '../network/api_client.dart';

class SyncManager {
  final DatabaseHelper _db = DatabaseHelper.instance;
  final ApiClient _api = ApiClient();
  bool _isSyncing = false;

  bool get isSyncing => _isSyncing;

  Future<int> syncPendingReports() async {
    if (_isSyncing) return 0;
    _isSyncing = true;
    int syncedCount = 0;

    try {
      final pending = await _db.getPendingReports();
      for (final report in pending) {
        try {
          await _api.post('reports', {
            'report_type': report['report_type'],
            'severity': report['severity'],
            'description': report['description'],
            'latitude': report['latitude'],
            'longitude': report['longitude'],
            'created_at': report['created_at'],
          });
          await _db.markReportSynced(report['id']);
          syncedCount++;
        } catch (e) {
          // Network failed or offline, leave in pending state
          break;
        }
      }
    } finally {
      _isSyncing = false;
    }
    return syncedCount;
  }

  Future<void> fetchAndCacheLatestAlerts() async {
    try {
      final List<dynamic> alerts = await _api.get('alerts?limit=20');
      for (final a in alerts) {
        await _db.insertAlert({
          'id': a['id'],
          'severity': a['severity'],
          'title': a['title'],
          'message': a['message'],
          'issued_at': a['issued_at'],
          'status': a['status'],
          'is_read': 0,
        });
      }
    } catch (_) {
      // Offline fallback: alerts in SQLite remain cached
    }
  }
}
