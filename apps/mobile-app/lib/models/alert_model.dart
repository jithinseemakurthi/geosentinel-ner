class AlertModel {
  final String id;
  final String severity;
  final String title;
  final String message;
  final String issuedAt;
  final String status;
  final bool isRead;

  AlertModel({
    required this.id,
    required this.severity,
    required this.title,
    required this.message,
    required this.issuedAt,
    required this.status,
    this.isRead = false,
  });

  factory AlertModel.fromMap(Map<String, dynamic> map) {
    return AlertModel(
      id: map['id'],
      severity: map['severity'],
      title: map['title'],
      message: map['message'],
      issuedAt: map['issued_at'],
      status: map['status'],
      isRead: map['is_read'] == 1,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'severity': severity,
      'title': title,
      'message': message,
      'issued_at': issuedAt,
      'status': status,
      'is_read': isRead ? 1 : 0,
    };
  }
}
