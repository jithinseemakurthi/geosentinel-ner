import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import '../config/app_config.dart';

class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._init();
  static Database? _database;

  DatabaseHelper._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB(AppConfig.offlineDbName);
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, filePath);

    return await openDatabase(
      path,
      version: 1,
      onCreate: _createDB,
    );
  }

  Future _createDB(Database db, int version) async {
    // 1. Cached Alerts
    await db.execute('''
      CREATE TABLE alerts (
        id TEXT PRIMARY KEY,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        status TEXT NOT NULL,
        is_read INTEGER DEFAULT 0
      )
    ''');

    // 2. Pending Offline Citizen Reports Queue
    await db.execute('''
      CREATE TABLE offline_reports (
        id TEXT PRIMARY KEY,
        report_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        photo_path TEXT,
        created_at TEXT NOT NULL,
        sync_status TEXT DEFAULT 'pending'
      )
    ''');

    // 3. Cached Risk Zones
    await db.execute('''
      CREATE TABLE risk_zones (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        state TEXT NOT NULL,
        district TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        risk_score REAL NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        updated_at TEXT NOT NULL
      )
    ''');
  }

  Future<void> insertAlert(Map<String, dynamic> row) async {
    final db = await instance.database;
    await db.insert('alerts', row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, dynamic>>> getCachedAlerts() async {
    final db = await instance.database;
    return await db.query('alerts', orderBy: 'issued_at DESC');
  }

  Future<void> queueOfflineReport(Map<String, dynamic> row) async {
    final db = await instance.database;
    await db.insert('offline_reports', row, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<Map<String, dynamic>>> getPendingReports() async {
    final db = await instance.database;
    return await db.query('offline_reports', where: 'sync_status = ?', whereArgs: ['pending']);
  }

  Future<void> markReportSynced(String id) async {
    final db = await instance.database;
    await db.update(
      'offline_reports',
      {'sync_status': 'synced'},
      where: 'id = ?',
      whereArgs: [id],
    );
  }
}
