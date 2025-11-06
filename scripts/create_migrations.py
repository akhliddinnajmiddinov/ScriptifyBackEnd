import os
import sys
import django
import subprocess

# Add the project root to the Python path
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'book_arena.settings')

def run_migrations():
    """Create and run Django migrations for the updated models"""
    
    print("Creating migrations for book app...")
    try:
        # Create migrations
        result = subprocess.run([
            sys.executable, 'manage.py', 'makemigrations', 'book'
        ], capture_output=True, text=True, cwd='/app')
        
        if result.returncode == 0:
            print("✅ Migrations created successfully")
            print(result.stdout)
        else:
            print("❌ Error creating migrations:")
            print(result.stderr)
            return False
            
        # Create migrations for user app
        print("\nCreating migrations for user app...")
        result = subprocess.run([
            sys.executable, 'manage.py', 'makemigrations', 'user'
        ], capture_output=True, text=True, cwd='/app')
        
        if result.returncode == 0:
            print("✅ User migrations created successfully")
            print(result.stdout)
        else:
            print("❌ Error creating user migrations:")
            print(result.stderr)
            
        # Run migrations
        print("\nRunning migrations...")
        result = subprocess.run([
            sys.executable, 'manage.py', 'migrate'
        ], capture_output=True, text=True, cwd='/app')
        
        if result.returncode == 0:
            print("✅ Migrations applied successfully")
            print(result.stdout)
            return True
        else:
            print("❌ Error applying migrations:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Error running migrations: {str(e)}")
        return False

if __name__ == '__main__':
    success = run_migrations()
    if success:
        print("\n🎉 Database setup completed successfully!")
    else:
        print("\n💥 Database setup failed. Please check the errors above.")
