import 'package:flutter_test/flutter_test.dart';
import 'package:geosentinel_mobile/models/alert_model.dart';
import 'package:geosentinel_mobile/models/citizen_report_model.dart';

void main() {
  group('AlertModel Tests', () {
    test('toMap and fromMap should correctly serialize and deserialize', () {
      final alert = AlertModel(
        id: 'alt_123',
        severity: 'warning',
        title: 'Heavy Rain Warning',
        message: 'Precipitation exceeding 75mm.',
        issuedAt: '2026-09-02T10:00:00Z',
        status: 'active',
        isRead: false,
      );

      final map = alert.toMap();
      expect(map['id'], 'alt_123');
      expect(map['severity'], 'warning');
      expect(map['is_read'], 0);

      final restored = AlertModel.fromMap(map);
      expect(restored.id, alert.id);
      expect(restored.title, alert.title);
      expect(restored.isRead, false);
    });
  });

  group('CitizenReportModel Tests', () {
    test('toMap and fromMap should serialize correctly with pending status', () {
      final report = CitizenReportModel(
        id: 'rep_456',
        reportType: 'crack',
        severity: 'critical',
        description: 'Large fissure opening on road edge.',
        latitude: 23.7271,
        longitude: 92.7176,
        createdAt: '2026-09-02T10:05:00Z',
      );

      final map = report.toMap();
      expect(map['report_type'], 'crack');
      expect(map['severity'], 'critical');
      expect(map['sync_status'], 'pending');

      final restored = CitizenReportModel.fromMap(map);
      expect(restored.id, 'rep_456');
      expect(restored.latitude, 23.7271);
      expect(restored.syncStatus, 'pending');
    });
  });
}
