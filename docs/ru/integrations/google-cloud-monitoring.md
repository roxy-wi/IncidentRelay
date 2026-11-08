# Google Cloud Monitoring

Алерты из Google Cloud Monitoring можно отправлять прямо в IncidentRelay через [Webhook версии 1.2](https://docs.cloud.google.com/monitoring/support/notification-options#webhooks). Для этого не нужны Pub/Sub и Cloud Functions.

1. В **Routes** создайте маршрут с источником **Google Cloud Monitoring**, выберите команду и сохраните. Скопируйте токен приёма.
2. В Google Cloud Console откройте **Monitoring → Alerting → Edit notification channels** и добавьте канал **Webhook**. Укажите доступный извне HTTPS-адрес `https://ir.example.com/api/integrations/google-cloud-monitoring`. Выберите **HTTP Basic**: имя пользователя — `incidentrelay`, пароль — токен маршрута. Не добавляйте токен в URL.
3. Привяжите канал к политике алертинга и включите уведомления о закрытии. Иначе IR узнает об открытии алерта, но не о восстановлении.

### Проверка маршрута

Сохраните пример в `incident.json` и отправьте его в тестовый маршрут. Команда запросит токен как пароль.

```json
{
  "version": "1.2",
  "incident": {
    "incident_id": "ir-test-001",
    "scoping_project_id": "example-project",
    "state": "open",
    "policy_name": "Checkout error rate",
    "severity": "Error",
    "resource": {"type": "cloud_run_revision"},
    "summary": "Checkout returned HTTP 500"
  }
}
```

```sh
curl --user incidentrelay -H 'Content-Type: application/json' \
  --data-binary @incident.json https://ir.example.com/api/integrations/google-cloud-monitoring
```

Отправьте файл дважды: повтор обновит тот же алерт. Замените `state` на `closed` и отправьте ещё раз — алерт закроется. Запоздалый `open` с тем же проектом и ID на этом маршруте будет проигнорирован, даже если закрытие пришло первым. Чтобы повторить проверку, используйте новый ID.

Проект и ID инцидента Google обязательны. Для группировки используйте `gcp_project_id` и `gcp_incident_id`. Если Google передал данные политики, условия или ресурса, появятся метки `gcp_policy`, `gcp_condition`, `gcp_resource_type`, `gcp_resource_name`. Если передан URL Google Cloud Console, из алерта можно перейти к исходному инциденту. Уровни важности: Critical → critical, Error → high, Warning → warning; отсутствующий или неизвестный уровень → info.

**200** означает, что алерт обработан. **202** — группа не создана, например, при получении запоздалого уведомления. При **401** проверьте имя пользователя, токен и состояние маршрута; при **400** — источник маршрута, версию формата, проект, ID и состояние инцидента.
