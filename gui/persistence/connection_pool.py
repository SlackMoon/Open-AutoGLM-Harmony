"""Database connection pool for thread-safe access."""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from queue import Queue, Empty
from typing import Generator

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe SQLite connection pool."""
    
    def __init__(self, db_path: str, pool_size: int = 5):
        """Initialize connection pool.
        
        Args:
            db_path: Path to SQLite database
            pool_size: Number of connections in pool
        """
        self.db_path = Path(db_path)
        self.pool_size = pool_size
        self.connections: Queue = Queue(maxsize=pool_size)
        self.lock = threading.Lock()
        self._initialized = False
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Create and configure all connections in the pool."""
        with self.lock:
            if self._initialized:
                return
            
            logger.info(f"Initializing connection pool with {self.pool_size} connections")
            
            for i in range(self.pool_size):
                conn = self._create_connection()
                self.connections.put(conn)
            
            self._initialized = True
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimal settings.
        
        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,  # Allow use from multiple threads
            timeout=10.0,  # 10 second timeout
        )
        
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")
        
        # Set synchronous mode to NORMAL for better performance
        conn.execute("PRAGMA synchronous=NORMAL")
        
        # Set cache size (negative value = KB, positive = pages)
        conn.execute("PRAGMA cache_size=-10000")  # 10MB cache
        
        logger.debug(f"Created new database connection to {self.db_path}")
        
        return conn
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool (context manager).
        
        Yields:
            Database connection
            
        Example:
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tasks")
        """
        conn = None
        try:
            # Get connection from pool (blocks if pool is empty)
            conn = self.connections.get(timeout=5.0)
            yield conn
        except Empty:
            logger.error("Connection pool exhausted - timeout waiting for connection")
            raise RuntimeError("Database connection pool exhausted")
        finally:
            # Return connection to pool
            if conn is not None:
                self.connections.put(conn)
    
    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            if not self._initialized:
                return
            
            logger.info("Closing all connections in pool")
            
            # Drain the queue and close all connections
            closed_count = 0
            while not self.connections.empty():
                try:
                    conn = self.connections.get_nowait()
                    conn.close()
                    closed_count += 1
                except Empty:
                    break
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            
            logger.info(f"Closed {closed_count} connections")
            self._initialized = False
    
    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close_all()
        except Exception:
            pass  # Ignore errors during cleanup
