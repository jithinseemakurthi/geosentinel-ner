import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/i18n/app_translations.dart';
import '../widgets/risk_badge.dart';
import '../widgets/sos_button.dart';

class HomeScreen extends StatelessWidget {
  final String language;
  final VoidCallback onNavigateToMap;
  final VoidCallback onNavigateToReport;

  const HomeScreen({
    Key? key,
    this.language = 'en',
    required this.onNavigateToMap,
    required this.onNavigateToReport,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Current Risk Status Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        AppTranslations.get('risk_level', lang: language),
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      const RiskBadge(riskLevel: 'Warning'),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Aizawl Ridge Sector 4',
                    style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Observed Rain: 65mm | 24h Forecast: 90mm | Slope Risk: 78%',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
                  ),
                  const SizedBox(height: 20),
                  SosButton(
                    onPressed: () {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('SOS Alert Broadcasted to SEOC & Local Officers'),
                          backgroundColor: AppColors.evacuation,
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Quick Action Buttons
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                  ),
                  onPressed: onNavigateToMap,
                  icon: const Icon(Icons.map),
                  label: Text(AppTranslations.get('map', lang: language)),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    backgroundColor: AppColors.secondary,
                    foregroundColor: Colors.white,
                  ),
                  onPressed: onNavigateToReport,
                  icon: const Icon(Icons.add_a_photo),
                  label: Text(AppTranslations.get('report', lang: language)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),

          // Recent Regional Weather Advisory
          const Text(
            'North East Regional Advisory',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
          ),
          const SizedBox(height: 10),
          Card(
            child: ListTile(
              leading: const Icon(Icons.thunderstorm, color: AppColors.warning, size: 36),
              title: const Text('Heavy Monsoon Inundation Watch'),
              subtitle: const Text('Mizoram, Meghalaya & South Assam mountain slopes on high alert.'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () {},
            ),
          ),
        ],
      ),
    );
  }
}
