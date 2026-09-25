import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

class SosButton extends StatelessWidget {
  final VoidCallback onPressed;

  const SosButton({Key? key, required this.onPressed}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return ElevatedButton.icon(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.evacuation,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(30),
        ),
        elevation: 4,
      ),
      onPressed: onPressed,
      icon: const Icon(Icons.emergency, size: 24),
      label: const Text(
        'EMERGENCY SOS',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 1),
      ),
    );
  }
}
