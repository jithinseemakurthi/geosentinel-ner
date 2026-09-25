import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class ApiClient {
  final http.Client _client = http.Client();
  String? _authToken;

  void setAuthToken(String token) {
    _authToken = token;
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (_authToken != null) 'Authorization': 'Bearer $_authToken',
      };

  Future<dynamic> get(String endpoint) async {
    final url = Uri.parse('${AppConfig.apiBaseUrl}/$endpoint');
    final response = await _client.get(url, headers: _headers);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return json.decode(response.body);
    }
    throw Exception('API Error: ${response.statusCode} - ${response.body}');
  }

  Future<dynamic> post(String endpoint, Map<String, dynamic> data) async {
    final url = Uri.parse('${AppConfig.apiBaseUrl}/$endpoint');
    final response = await _client.post(
      url,
      headers: _headers,
      body: json.encode(data),
    );
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return json.decode(response.body);
    }
    throw Exception('API Error: ${response.statusCode} - ${response.body}');
  }
}
