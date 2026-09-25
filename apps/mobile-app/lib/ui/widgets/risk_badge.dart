import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

class RiskBadge extends StatelessWidget {
  final String riskLevel;

  const RiskBadge({Key? key, required this.riskLevel}) : super(key: key);

  Color _getColor() {
    switch (riskLevel.toLowerCase()) {
      case 'evacuation':
      case 'critical':
        return AppColors.evacuation;
      case 'warning':
      case 'high':
        return AppColors.warning;
      case 'watch':
      case 'moderate':
        return AppColors.watch;
      default:
        return AppColors.advisory;
    }
  }

  @override
  Widget build(BuildContext context) {
    final color = _getColor();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color, width: 1.5),
      ),
      child: Text(
        riskLevel.toUpperCase(),
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      ),
    );
  }
}
