---
title: Безопасность голосового провайдера
description: Рекомендации по безопасности для пользовательских голосовых провайдеров
---

# Безопасность голосового провайдера

Пользовательские провайдеры — это исполняемый Python-код.

Устанавливайте провайдеры только из доверенных источников.

## Права доступа к каталогу

Рекомендуемые права доступа:

```bash
sudo mkdir -p /usr/local/lib/incidentrelay/voice_providers
sudo chown root:root /usr/local/lib/incidentrelay/voice_providers
sudo chmod 755 /usr/local/lib/incidentrelay/voice_providers
```

Каталог провайдеров не должен быть доступен для записи:

- пользователю веб-сервера;
- пользователю приложения IncidentRelay;
- недоверенным пользователям;
- из интерфейса IncidentRelay.

## Секреты

Не задавайте секреты жёстко в файлах провайдеров.

Плохо:

```python
api_token = "secret-token"
```

Хорошо:

```json
"provider_config": {
  "api_token": "${VOICE_API_TOKEN}"
}
```

Затем настройте переменную окружения для сервиса IncidentRelay:

```bash
export VOICE_API_TOKEN="secret-token"
```

Для systemd используйте файл окружения или конфигурацию окружения сервиса.

Пример:

```ini
Environment="VOICE_API_TOKEN=secret-token"
```

## Журналирование

Провайдеры могут журналировать полезную операционную информацию, но не должны журналировать секреты или полные номера телефонов.

Хорошо:

```python
import logging

logger = logging.getLogger("oncall.voice")


def mask_phone(phone):
    if not phone:
        return None

    value = str(phone)

    if len(value) <= 4:
        return "****"

    return f"***{value[-4:]}"


logger.info(
    "placing voice call",
    extra={
        "extra": {
            "provider": self.name,
            "phone": mask_phone(request.phone),
            "alert_id": request.alert_id,
            "event_type": request.event_type,
        }
    },
)
```

Плохо:

```python
logger.info(f"calling {request.phone} with token {self.config['api_token']}")
```

## Секреты колбэков

Секреты колбэков должны быть уникальными и трудно угадываемыми.

Используйте секреты на уровне канала, когда это возможно:

```json
{
  "callback_secret": "long-random-secret"
}
```

Избегайте коротких секретов:

```text
test
123
secret
change-me
```

## Подписи вебхуков провайдера

Если ваш провайдер подписывает колбэки, проверяйте подпись внутри `parse_callback()`.

Пример:

```python
def parse_callback(self, payload, headers=None, raw_body=None, query_args=None):
    signature = headers.get("X-Provider-Signature") if headers else None

    if not self._is_valid_signature(raw_body or b"", signature):
        raise RuntimeError("invalid provider callback signature")

    ...
```

## Рекомендуемые правила

```text
- The providers directory must not be writable by the web server user.
- The providers directory must not be writable from the IncidentRelay UI.
- Provider files should be reviewed before installation.
- Secrets should be passed through environment variables.
- Provider logs must not contain API tokens, passwords or full phone numbers.
- Callback secrets should be unique and hard to guess.
- Provider-specific webhook signatures should be validated when supported.
```

Не позволяйте недоверенным пользователям загружать файлы провайдеров.
