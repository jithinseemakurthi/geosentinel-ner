class CitizenReportModel {
  final String id;
  final String reportType;
  final String severity;
  final String description;
  final double latitude;
  final double longitude;
  final String? photoPath;
  final String createdAt;
  final String syncStatus;

  CitizenReportModel({
    required this.id,
    required this.reportType,
    required this.severity,
    required this.description,
    required this.latitude,
    required this.longitude,
    this.photoPath,
    required this.createdAt,
    this.syncStatus = 'pending',
  });

  factory CitizenReportModel.fromMap(Map<String, dynamic> map) {
    return CitizenReportModel(
      id: map['id'],
      reportType: map['report_type'],
      severity: map['severity'],
      description: map['description'] ?? '',
      latitude: map['latitude'],
      longitude: map['longitude'],
      photoPath: map['photo_path'],
      createdAt: map['created_at'],
      syncStatus: map['sync_status'] ?? 'pending',
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'report_type': reportType,
      'severity': severity,
      'description': description,
      'latitude': latitude,
      'longitude': longitude,
      'photo_path': photoPath,
      'created_at': createdAt,
      'sync_status': syncStatus,
    };
  }
}
