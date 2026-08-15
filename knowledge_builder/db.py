import pymysql
from typing import List, Tuple
import json
import os, sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from global_config import DB_CONFIG_BASE, DB_NAME, DB_CONFIG


def create_database_if_not_exists():
    """Connect to MySQL and create database if it doesn't exist"""
    with pymysql.connect(**DB_CONFIG_BASE) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"""
                CREATE DATABASE IF NOT EXISTS {DB_NAME}
                CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
            """)


def get_connection():
    """Get connection to target database"""
    return pymysql.connect(**DB_CONFIG)


def init_db():
    """Initialize database table structure"""
    try:
        create_database_if_not_exists()

        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Create top_level table (avoid TEXT in UNIQUE)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS top_level (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        package_name VARCHAR(255) NOT NULL,
                        package_version VARCHAR(255) NOT NULL,
                        top_level VARCHAR(1024) NOT NULL,
                        version_id INT DEFAULT 0,
                        UNIQUE KEY uniq_top_level (package_name(100), package_version(100), top_level(191))
                    )
                """)
                # Create api_signatures table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_signatures (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        package_name VARCHAR(255) NOT NULL,
                        package_version VARCHAR(255) NOT NULL,
                        api_name VARCHAR(1024) NOT NULL,
                        parameters TEXT,
                        has_return TINYINT(1) NOT NULL,
                        UNIQUE KEY uniq_api (package_name(100), package_version(100), api_name(191))
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS differences (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        package_version INT NOT NULL,
                        package_name VARCHAR(255) NOT NULL,
                        version_id INT NOT NULL,
                        api_name TEXT NOT NULL,
                        param_list TEXT,
                        has_return BOOLEAN,
                        diff CHAR(1) NOT NULL,
                        FOREIGN KEY (package_version) REFERENCES top_level(id) ON DELETE CASCADE
                    )
                """)

                # Create indexes (must use SHOW to check, IF NOT EXISTS not supported)
                cursor.execute("SHOW INDEX FROM api_signatures WHERE Key_name = 'idx_api_signatures_pkg_ver'")
                if cursor.fetchone() is None:
                    cursor.execute("CREATE INDEX idx_api_signatures_pkg_ver ON api_signatures(package_name(100), package_version(100))")

                cursor.execute("SHOW INDEX FROM api_signatures WHERE Key_name = 'idx_api_signatures_name'")
                if cursor.fetchone() is None:
                    cursor.execute("CREATE INDEX idx_api_signatures_name ON api_signatures(api_name(191))")
    except Exception as e:
        print(f"Database initialization failed: {e}")
    

def is_exist(sql, params=()):
    """Check if record exists"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone() is not None


def insert_many(sql_list):
    """Batch execute INSERT statements"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for sql in sql_list:
                try:
                    cursor.execute(sql)
                except pymysql.IntegrityError:
                    pass


def save_api_signatures(package_name: str, version: str, signatures: List[Tuple[str, List[str], bool]]):
    """Save API signatures to database"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            for api_name, params, has_return in signatures:
                try:
                    cursor.execute(
                        """INSERT INTO api_signatures 
                        (package_name, package_version, api_name, parameters, has_return)
                        VALUES (%s, %s, %s, %s, %s)""",
                        (package_name, version, api_name, json.dumps(params), 1 if has_return else 0)
                    )
                except pymysql.IntegrityError:
                    continue


def get_api_signatures(package_name: str, version: str = None):
    """Get API signatures for a given package and version"""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if version:
                cursor.execute(
                    """SELECT api_name, parameters, has_return 
                    FROM api_signatures 
                    WHERE package_name=%s AND package_version=%s""",
                    (package_name, version)
                )
            else:
                cursor.execute(
                    """SELECT api_name, parameters, has_return 
                    FROM api_signatures 
                    WHERE package_name=%s""",
                    (package_name,)
                )

            results = []
            for api_name, params_json, has_return in cursor.fetchall():
                params = json.loads(params_json) if params_json else []
                results.append((api_name, params, bool(has_return)))
            return results


# Initialize database (auto-create tables on first import)
if __name__ == "__main__":
    init_db()
    print("MySQL database and table structure initialized")
