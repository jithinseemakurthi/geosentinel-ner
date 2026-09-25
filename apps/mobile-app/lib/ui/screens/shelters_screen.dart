import 'package:flutter/material.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';

class SheltersScreen extends StatelessWidget {
  const SheltersScreen({Key? key}) : super(key: key);

  final List<Map<String, dynamic>> mockShelters = const [
    {
      'name': 'Government Higher Secondary School',
      'location': 'Khatla, Aizawl',
      'capacity': 350,
      'distance': '1.2 km',
      'has_medical': true,
      'contact': '+91-389-2322222',
    },
    {
      'name': 'Community Disaster Relief Center',
      'location': 'Mission Veng, Aizawl',
      'capacity': 500,
      'distance': '2.8 km',
      'has_medical': true,
      'contact': '+91-389-2323333',
    },
    {
      'name': 'District Indoor Sports Stadium',
      'location': 'Zarkawt, Aizawl',
      'capacity': 800,
      'distance': '4.1 km',
      'has_medical': false,
      'contact': '+91-389-2324444',
    },
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Emergency Contacts Section
          const Text(
            'Emergency Helplines',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
          ),
          const SizedBox(height: 10),
          Card(
            child: Column(
              children: AppConfig.emergencyHelplines.entries.map((entry) {
                return ListTile(
                  leading: const CircleAvatar(
                    backgroundColor: AppColors.evacuation,
                    child: Icon(Icons.phone, color: Colors.white, size: 20),
                  ),
                  title: Text(entry.key, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
                  trailing: Text(
                    entry.value,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: AppColors.evacuation,
                    ),
                  ),
                  onTap: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Dialing ${entry.key}: ${entry.value}')),
                    );
                  },
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 20),

          // Designated Evacuation Shelters
          const Text(
            'Designated Evacuation Shelters',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textPrimary),
          ),
          const SizedBox(height: 10),
          ...mockShelters.map((s) {
            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              child: ListTile(
                leading: const CircleAvatar(
                  backgroundColor: AppColors.secondary,
                  child: Icon(Icons.night_shelter, color: Colors.white),
                ),
                title: Text(s['name'], style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text('${s['location']} • Distance: ${s['distance']}\nCapacity: ${s['capacity']} people'),
                isThreeLine: true,
                trailing: IconButton(
                  icon: const Icon(Icons.directions, color: AppColors.secondary),
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Opening safe evacuation navigation to ${s['name']}')),
                    );
                  },
                ),
              ),
            );
          }).toList(),
        ],
      ),
    );
  }
}
