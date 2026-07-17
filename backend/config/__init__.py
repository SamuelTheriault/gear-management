import pymysql

# Django attend l'API mysqlclient ; PyMySQL (pur Python, sans dépendance
# système à compiler) s'y fait passer pour éviter d'avoir à installer
# libmysqlclient-dev en local comme sur l'hébergement.
pymysql.install_as_MySQLdb()
