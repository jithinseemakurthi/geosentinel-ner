UPDATE app_user SET password_hash = '$2b$12$QDSLp3jJB1F/yRgHZwtgOeGEt3fKGBei5WwVMeye9h0SYs7UDesaS' WHERE username='admin';
SELECT username, is_active FROM app_user WHERE username='admin';
