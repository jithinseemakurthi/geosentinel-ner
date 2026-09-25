import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../widgets/risk_badge.dart';

class AlertsScreen extends StatelessWidget {
  const AlertsScreen({Key? key}) : super(key: key);

  final List<Map<String, String>> mockAlerts = const [
    {
      'id': 'alt_001',
      'severity': 'evacuation',
      'title': 'IMMEDIATE EVACUATION: Aizawl Ridge Sector 4',
      'message': 'Severe debris flow risk detected following 95mm cumulative rainfall. Move to designated community shelters immediately.',
      'issued_at': '10 mins ago',
      'status': 'active',
    },
    {
      'id': 'alt_002',
      'severity': 'warning',
      'title': 'LANDSLIDE WARNING: NH-54 Road Blockage Risk',
      'message': 'Crack propagation observed on hillside slope near km 34. Avoid heavy vehicular movement.',
      'issued_at': '45 mins ago',
      'status': 'active',
    },
    {
      'id': 'alt_003',
      'severity': 'watch',
      'title': 'WEATHER WATCH: Shillong Peak District',
      'message': 'Continuous light-to-moderate showers expected over next 24 hours. Antecedent moisture elevated.',
      'issued_at': '2 hours ago',
      'status': 'acknowledged',
    },
  ];

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: mockAlerts.length,
      itemBuilder: (context, index) {
        final alert = mockAlerts[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    RiskBadge(riskLevel: alert['severity']!),
                    Text(
                      alert['issued_at']!,
                      style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  alert['title']!,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  alert['message']!,
                  style: const TextStyle(
                    fontSize: 14,
                    color: AppColors.textSecondary,
                    height: 1.3,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
