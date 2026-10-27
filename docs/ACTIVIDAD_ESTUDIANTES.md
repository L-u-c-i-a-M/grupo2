# Práctica Profesionalizante I
## Despliegue y operación de OpsCenter

El equipo recibe un servicio terminado. La tarea no consiste en desarrollar nuevas funcionalidades sino en desplegarlo, verificarlo y dejarlo operable.

1. Ingresar por SSH y reconocer el entorno.
2. Clonar el repositorio e identificar el commit.
3. Crear `.venv` e instalar dependencias.
4. Crear `.env` a partir de `.env.example`.
5. Ejecutar Uvicorn en `127.0.0.1` y el puerto asignado.
6. Verificar `/live`, `/ready`, `/health` y `/version`.
7. Abrir el dashboard y registrar un incidente y un evento.
8. Verificar el dominio HTTPS a través de CloudPanel/NGINX.
9. Instalar el servicio systemd de usuario.
10. Ejecutar `scripts/verify-service.sh`.
11. Diagnosticar un incidente introducido por el docente.
