import 'package:flutter/material.dart';
import 'core/theme/app_theme.dart';
import 'core/i18n/app_translations.dart';
import 'ui/widgets/offline_banner.dart';
import 'ui/screens/home_screen.dart';
import 'ui/screens/map_screen.dart';
import 'ui/screens/alerts_screen.dart';
import 'ui/screens/report_screen.dart';
import 'ui/screens/shelters_screen.dart';
import 'ui/screens/settings_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const GeoSentinelApp());
}

class GeoSentinelApp extends StatefulWidget {
  const GeoSentinelApp({Key? key}) : super(key: key);

  @override
  State<GeoSentinelApp> createState() => _GeoSentinelAppState();
}

class _GeoSentinelAppState extends State<GeoSentinelApp> {
  String _currentLanguage = 'en';

  void _changeLanguage(String newLang) {
    setState(() {
      _currentLanguage = newLang;
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GeoSentinel-NER',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      home: MainNavigationScaffold(
        currentLanguage: _currentLanguage,
        onLanguageChanged: _changeLanguage,
      ),
    );
  }
}

class MainNavigationScaffold extends StatefulWidget {
  final String currentLanguage;
  final ValueChanged<String> onLanguageChanged;

  const MainNavigationScaffold({
    Key? key,
    required this.currentLanguage,
    required this.onLanguageChanged,
  }) : super(key: key);

  @override
  State<MainNavigationScaffold> createState() => _MainNavigationScaffoldState();
}

class _MainNavigationScaffoldState extends State<MainNavigationScaffold> {
  int _currentIndex = 0;
  final bool _isOffline = true; // Demonstrates offline-first banner

  @override
  Widget build(BuildContext context) {
    final List<Widget> screens = [
      HomeScreen(
        language: widget.currentLanguage,
        onNavigateToMap: () => setState(() => _currentIndex = 1),
        onNavigateToReport: () => setState(() => _currentIndex = 3),
      ),
      const MapScreen(),
      const AlertsScreen(),
      const ReportScreen(),
      const SheltersScreen(),
      SettingsScreen(
        currentLanguage: widget.currentLanguage,
        onLanguageChanged: widget.onLanguageChanged,
      ),
    ];

    final titles = [
      AppTranslations.get('home', lang: widget.currentLanguage),
      AppTranslations.get('map', lang: widget.currentLanguage),
      AppTranslations.get('alerts', lang: widget.currentLanguage),
      AppTranslations.get('report', lang: widget.currentLanguage),
      AppTranslations.get('shelters', lang: widget.currentLanguage),
      AppTranslations.get('settings', lang: widget.currentLanguage),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text('${AppTranslations.get('app_title', lang: widget.currentLanguage)} • ${titles[_currentIndex]}'),
      ),
      body: Column(
        children: [
          if (_isOffline) const OfflineBanner(),
          Expanded(child: screens[_currentIndex]),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        selectedItemColor: AppColors.secondary,
        unselectedItemColor: AppColors.textSecondary,
        type: BottomNavigationBarType.fixed,
        onTap: (index) => setState(() => _currentIndex = index),
        items: [
          BottomNavigationBarItem(
            icon: const Icon(Icons.home),
            label: AppTranslations.get('home', lang: widget.currentLanguage),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.map),
            label: AppTranslations.get('map', lang: widget.currentLanguage),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.notifications),
            label: AppTranslations.get('alerts', lang: widget.currentLanguage),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.report_problem),
            label: AppTranslations.get('report', lang: widget.currentLanguage),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.shield),
            label: AppTranslations.get('shelters', lang: widget.currentLanguage),
          ),
          BottomNavigationBarItem(
            icon: const Icon(Icons.settings),
            label: AppTranslations.get('settings', lang: widget.currentLanguage),
          ),
        ],
      ),
    );
  }
}
