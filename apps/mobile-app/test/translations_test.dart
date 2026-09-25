import 'package:flutter_test/flutter_test.dart';
import 'package:geosentinel_mobile/core/i18n/app_translations.dart';

void main() {
  group('AppTranslations Tests', () {
    test('should provide English keys by default', () {
      expect(AppTranslations.get('app_title', lang: 'en'), 'GeoSentinel-NER');
      expect(AppTranslations.get('advisory', lang: 'en'), 'Normal / Low Risk');
      expect(AppTranslations.get('evacuation', lang: 'en'), 'Evacuation / High Danger');
    });

    test('should provide Hindi translations', () {
      expect(AppTranslations.get('app_title', lang: 'hi'), 'जियोसेंटिनल-एनईआर');
      expect(AppTranslations.get('report', lang: 'hi'), 'भूस्खलन रिपोर्ट करें');
    });

    test('should provide Mizo translations', () {
      expect(AppTranslations.get('advisory', lang: 'lus'), 'Him');
      expect(AppTranslations.get('evacuation', lang: 'lus'), 'Tlan chhuah hun');
    });

    test('should fallback to English if key is missing in target language', () {
      expect(AppTranslations.get('home', lang: 'nonexistent'), 'Home');
    });
  });
}
