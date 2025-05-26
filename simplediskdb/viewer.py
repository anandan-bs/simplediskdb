"""Flask application for viewing and querying diskcache databases."""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import os
import argparse
from logging import getLogger

from .db import DiskDB

logger = getLogger(__name__)

# Status type definitions
STATUS_TYPES = {
    'running': {'class': 'status-pending', 'description': 'Task is currently running'},
    'error': {'class': 'status-error', 'description': 'Task encountered an error'},
    'warning': {'class': 'status-pending', 'description': 'Task completed with warnings'},
    'initialized': {'class': 'status-pending', 'description': 'Task is initialized'},
    'completed': {'class': 'status-success', 'description': 'Task completed successfully'},
    'tracking_error': {'class': 'status-error', 'description': 'Task has tracking errors'},
    'failed': {'class': 'status-error', 'description': 'Task failed'}
}

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.secret_key = "simplediskdb"  # Change this in production

# Secret key for delete operations - this should be changed in production
DELETE_SECRET_KEY = "simplediskdb"  # Change this in production


@app.template_filter('datetime')
def format_datetime(value):
    """Format datetime objects or strings for display."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return value


@app.context_processor
def utility_processor():
    """Add utility functions to template context."""
    return {
        'get_status_info': lambda status: STATUS_TYPES.get(status.lower(), {
            'class': 'status-pending',
            'description': 'Unknown status'
        }) if status else {
            'class': 'status-pending',
            'description': 'No status'
        }
    }


def get_field_types(documents: List[Dict]) -> Dict[str, Set[str]]:
    """Get all possible field types from documents.

    Args:
        documents: List of documents to analyze

    Returns:
        Dictionary mapping field names to their possible types
    """
    # Define ordered fields and their types
    ordered_fields = [
        '_id',
        'issue_number',
        'created_at',
        'last_updated_at',
        'status',
        'traceback',
        'files'
    ]

    # Get field types while maintaining order
    field_types = {}
    for field in ordered_fields:
        field_types[field] = set()  # Initialize with empty set

    # Collect all possible types for each field
    for doc in documents:
        for field, value in doc.items():
            if field not in field_types:
                field_types[field] = set()
            field_types[field].add(type(value).__name__)

    return field_types


def format_value(value: Any) -> str:
    """Format a value for display in the table.

    Args:
        value: Value to format

    Returns:
        Formatted string representation of the value
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    elif isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    elif value is None:
        return 'N/A'
    return str(value)


@app.route('/', methods=['GET', 'POST'])
def index():
    """Home page - ask for diskcache location and database name."""
    if request.method == 'POST':
        cache_dir = request.form.get('cache_dir')
        collection_name = request.form.get('collection_name')

        if not cache_dir or not collection_name:
            flash('Please provide both cache directory and collection name', 'danger')
            return render_template('index.html')

        try:
            # Verify the cache directory exists
            if not os.path.isdir(cache_dir):
                flash('Cache directory does not exist', 'danger')
                return render_template('index.html')

            # Store in session
            session['cache_dir'] = cache_dir
            session['collection_name'] = collection_name

            return redirect(url_for('view_documents'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return render_template('index.html')

    return render_template('index.html', cache_dir='')


@app.route('/list_collections', methods=['POST'])
def list_dbs():
    """List all collections in the database."""
    data = request.get_json()
    if not data or 'cache_dir' not in data:
        return jsonify({'error': 'Cache directory not provided'}), 400

    try:
        db_obj = DiskDB(data['cache_dir'])
        collections = db_obj.list_collections()
        return jsonify({'collections': collections})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/documents')
def view_documents():
    """View recent documents from the database."""
    cache_dir = session.get('cache_dir')
    collection_name = session.get('collection_name')
    if not cache_dir or not collection_name:
        return redirect(url_for('index'))

    db_obj = DiskDB(cache_dir)
    collection = db_obj.get_collection(collection_name)
    if not collection:
        return render_template('error.html', message='Could not connect to database')

    # Get last 10 documents sorted by last_updated_at if it exists
    try:
        documents = collection.find_many(sort=[('last_updated_at', -1)], limit=10)
    except Exception:
        documents = collection.find_many(limit=10)

    # Analyze field types
    field_types = get_field_types(documents)

    return render_template(
        'documents.html',
        documents=documents,
        field_types=field_types,
        format_value=format_value
    )


class QueryError(Exception):
    """Custom exception for query-related errors."""

    pass


class DeleteError(Exception):
    """Custom exception for delete operations."""

    pass


def parse_json_field(field_name: str, value: str) -> Any:
    """Parse a JSON field and provide helpful error messages.

    Args:
        field_name: Name of the field being parsed
        value: JSON string to parse

    Returns:
        Parsed JSON value

    Raises:
        QueryError: If the JSON is invalid
    """
    if not value.strip():
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        line_no = e.lineno
        col_no = e.colno
        lines = value.split('\n')
        if 0 <= line_no - 1 < len(lines):
            line = lines[line_no - 1]
            pointer = ' ' * (col_no - 1) + '^'
            context = f"Line {line_no}:\n{line}\n{pointer}"
        else:
            context = str(e)

        raise QueryError(
            f"Invalid JSON in {field_name}:\n"
            f"{context}\n"
            f"Hint: Check for missing quotes, commas, or brackets"
        )


@app.route('/query', methods=['GET', 'POST'])
def query():
    """Query interface for the database."""
    cache_dir = session.get('cache_dir')
    collection_name = session.get('collection_name')
    if not cache_dir or not collection_name:
        return redirect(url_for('index'))

    db = DiskDB(cache_dir)
    collection = db.get_collection(collection_name)
    if not collection:
        return render_template('error.html', message='Could not connect to collection')

    if request.method == 'POST':
        error = None
        results = []
        field_types = {}
        query_params = {
            'conditions': request.form.get('conditions', '{}'),
            'sort': request.form.get('sort', '{}'),
            'limit': request.form.get('limit', '10')
        }

        try:
            # Parse query parameters with better error handling
            conditions = parse_json_field(
                'conditions', query_params['conditions'])
            sort = parse_json_field('sort', query_params['sort'])

            try:
                limit = int(query_params['limit'])
                if limit < 1:
                    raise ValueError("Limit must be positive")
                if limit > 1000:
                    raise ValueError("Limit cannot exceed 1000")
            except ValueError as e:
                raise QueryError(f"Invalid limit: {str(e)}")

            # Execute query
            try:
                results = collection.find_many(
                    query=conditions,
                    sort=sort,
                    limit=limit
                )
            except Exception as e:
                raise QueryError(f"Database query failed: {str(e)}")

            # Analyze field types
            field_types = get_field_types(results)

            # Format the JSON nicely for display
            query_params['conditions'] = json.dumps(conditions, indent=2)
            query_params['sort'] = json.dumps(sort, indent=2)

        except QueryError as e:
            error = str(e)
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

        return render_template('query.html',
                               results=results,
                               field_types=field_types,
                               format_value=format_value,
                               query_params=query_params,
                               error=error)

    return render_template('query.html')


@app.route('/delete', methods=['POST'])
def delete_records():
    """Delete records matching the query conditions."""
    cache_dir = session.get('cache_dir')
    collection_name = session.get('collection_name')
    if not cache_dir or not collection_name:
        return jsonify({'error': 'No collection connection'}), 400

    try:
        # Verify secret key
        secret_key = request.form.get('secret_key')
        if not secret_key:
            raise DeleteError('Secret key is required')
        if secret_key != DELETE_SECRET_KEY:
            raise DeleteError('Invalid secret key')

        # Parse and validate query conditions
        conditions = parse_json_field(
            'conditions', request.form.get('conditions', '{}'))
        if not conditions:
            raise DeleteError('Cannot delete without query conditions')

        # Get database instance
        db = DiskDB(cache_dir)
        collection = db.get_collection(collection_name)
        if not collection:
            raise DeleteError('Could not connect to collection')

        # First get matching records count
        matching_records = collection.find_many(query=conditions)
        count = len(matching_records)
        if count == 0:
            raise DeleteError('No records match the query conditions')

        # Delete matching records
        try:
            import pdb;pdb.set_trace()
            deleted_count = collection.delete_many(query=conditions)

            if deleted_count != count:
                raise DeleteError(
                    f'Only deleted {deleted_count} out of {count} records')

            return jsonify({
                'success': True,
                'message': f'Successfully deleted {deleted_count} records'
            })
        except Exception as e:
            raise DeleteError(f'Error during deletion: {str(e)}')

    except DeleteError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Unexpected error: {str(e)}')
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


def main(host='127.0.0.1', port=5000):
    """Run the viewer application.
    
    Args:
        host (str): Host to bind the server to
        port (int): Port to run the server on
    """
    app.run(host=host, port=port)