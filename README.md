### Commands:

Command to activate the enviroment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Command to start the server:
```bash
python manage.py runserver
```

Command to make migration:
```bash
python manage.py makemigrations
```

Command to migrate:
```bash
python manage.py migrate
```

Command to add superuser to the Admin panel:
```bash
python manage.py createsuperuser
```

Pages:

http://127.0.0.1:8000/admin/ - admin panel login

http://127.0.0.1:8000/accounts/login/ - general login


Test accounts:

  Admin:
  
    UN: Vadim
    
    P: 7238523qwQW!
    
  User:
  
    UN: user
    
    P: useruser!!!

