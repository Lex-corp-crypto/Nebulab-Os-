-- Initial database setup for Distributed Linux Lab
-- This script runs when the PostgreSQL container starts

-- Create a default admin user (password: admin123)
-- In production, change this immediately!
INSERT INTO users (username, email, hashed_password)
VALUES ('admin', 'admin@distributedlab.local', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW')
ON CONFLICT (username) DO NOTHING;

-- Insert some initial machines for testing
INSERT INTO machines (hostname, ip_address, os_type, last_seen, is_active)
VALUES
('pop-os-machine', '192.168.1.100', 'pop_os', NOW(), TRUE),
('ubuntu-machine', '192.168.1.101', 'ubuntu', NOW(), TRUE)
ON CONFLICT DO NOTHING;