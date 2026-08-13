import os

from app import create_app


app = create_app()


if __name__ == '__main__':
    is_production = os.environ.get('FLASK_ENV', os.environ.get('ENV', 'development')).lower() in {'production', 'prod'}
    app.run(
        host=os.environ.get('HOST', '0.0.0.0'),
        port=int(os.environ.get('PORT', '5000')),
        debug=not is_production,
    )
