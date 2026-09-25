import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

class MapScreen extends StatelessWidget {
  const MapScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // Placeholder for MapLibre / FlutterMap layer
        Container(
          color: const Color(0xFFE2E8F0),
          child: Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.terrain, size: 64, color: AppColors.secondary),
                const SizedBox(height: 12),
                const Text(
                  'North East Landslide Hazard Map',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Offline Vector Tiles & Real-Time Risk Layers Loaded',
                  style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
                ),
              ],
            ),
          ),
        ),

        // Layer Control Floating Panel
        Positioned(
          top: 16,
          right: 16,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: const [
                  Icon(Icons.layers, size: 20, color: AppColors.primary),
                  SizedBox(width: 8),
                  Text('Rainfall Radar + Risk Zones', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}
