class AppConfig {
  static const String appName = 'GeoSentinel-NER';
  static const String appVersion = '1.0.0';
  static const String apiBaseUrl = 'https://api.geosentinel.in/api/v1';
  static const String offlineDbName = 'geosentinel_offline.db';
  static const int syncIntervalMinutes = 15;
  static const int maxOfflineReports = 500;
  
  // Emergency Helpline Numbers for North Eastern Region
  static const Map<String, String> emergencyHelplines = {
    'National Disaster Management (NDMA)': '1078',
    'State Emergency Operation Centre (SEOC)': '1070',
    'District Disaster Management (DDMA)': '1077',
    'Ambulance / Emergency Medical': '108',
    'Police Emergency': '112',
  };
}
