import 'package:flutter/material.dart';

class AppColors {
  static const Color primary = Color(0xFF0F172A);
  static const Color secondary = Color(0xFF0284C7);
  static const Color background = Color(0xFFF8FAFC);
  static const Color card = Colors.white;

  // Disaster Risk Color Coding
  static const Color advisory = Color(0xFF10B981); // Green
  static const Color watch = Color(0xFFF59E0B);    // Amber/Yellow
  static const Color warning = Color(0xFFF97316);  // Orange
  static const Color evacuation = Color(0xFFEF4444); // Red
  static const Color textPrimary = Color(0xFF1E293B);
  static const Color textSecondary = Color(0xFF64748B);
}

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.secondary,
        primary: AppColors.primary,
        background: AppColors.background,
      ),
      scaffoldBackgroundColor: AppColors.background,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: true,
      ),
      cardTheme: CardTheme(
        color: AppColors.card,
        elevation: 2,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
      ),
    );
  }
}
