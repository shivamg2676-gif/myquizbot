# Add this inside database.py
def get_user_linked_group(user_id):
    """Retrieve the linked group ID for a specific user."""
    # Example using SQLite (adjust table/column names to match your DB schema):
    cursor = conn.cursor()
    cursor.execute("SELECT linked_group_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None
