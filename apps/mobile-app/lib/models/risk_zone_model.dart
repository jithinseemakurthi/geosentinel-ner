class RiskZoneModel {
  final String id;
  final String name;
  final String state;
  final String district;
  final String riskLevel;
  final double riskScore;
  final double latitude;
  final double longitude;

  RiskZoneModel({
    required this.id,
    required this.name,
    required this.state,
    required this.district,
    required this.riskLevel,
    required this.riskScore,
    required this.latitude,
    required this.longitude,
  });

  factory RiskZoneModel.fromMap(Map<String, dynamic> map) {
    return RiskZoneModel(
      id: map['id'],
      name: map['name'],
      state: map['state'],
      district: map['district'],
      riskLevel: map['risk_level'],
      riskScore: map['risk_score'],
      latitude: map['latitude'],
      longitude: map['longitude'],
    );
  }
}
