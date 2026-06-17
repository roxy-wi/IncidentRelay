---
title: Quickstart Checklist
description: Checklist for validating a first IncidentRelay installation.
---

# Quickstart Checklist

Use this checklist after installation.

## Installation

- [ ] Installed with Docker, RPM, or manual systemd guide
- [ ] Config file exists
- [ ] `INCIDENTRELAY_CONFIG_FILE` points to the config file
- [ ] Web service is running
- [ ] Scheduler service is running
- [ ] Migrations have been applied with `python manage.py migrate`
- [ ] First global admin user exists

## Base configuration

- [ ] `public_base_url` is set to the real external URL
- [ ] Database settings are correct
- [ ] SMTP is configured globally if email channel will be used
- [ ] Voice provider is configured if voice calls will be used
- [ ] Browser push VAPID keys are configured if PWA/browser push will be used
- [ ] Logs are visible in journal, container logs, or log file

## RBAC and teams

- [ ] Group exists
- [ ] Users exist
- [ ] Users are added to the group
- [ ] Group roles are assigned: `viewer`, `editor`, `user_admin`
- [ ] Team exists
- [ ] Team users are added from the same group
- [ ] Team roles are assigned: `viewer`, `responder`, `manager`

## On-call setup

- [ ] Rotation exists
- [ ] Rotation members are in the correct order
- [ ] Reminder interval is configured:

```text
0 reminders disabled
>= 60 reminders enabled
```

- [ ] Escalation policy is configured on the team
- [ ] Calendar view shows expected on-call users

## Notification setup

- [ ] At least one notification channel exists
- [ ] Channel is enabled
- [ ] Channel severity filter is correct or empty
- [ ] Required user profile contact fields are filled
- [ ] Channel test works
- [ ] Responders who want browser push enabled it in Profile
- [ ] Browser push test works from Profile

Browser push is profile-level and does not need a channel or route binding.

## Route setup

- [ ] Route exists
- [ ] Route source matches incoming integration type
- [ ] Route is attached to one or more channels
- [ ] Route matcher matches incoming payload
- [ ] Route intake token is copied into monitoring system

## Validation

- [ ] Send a firing test alert
- [ ] Alert appears in Alerts page
- [ ] Notification is delivered
- [ ] ACK works for a responder/manager
- [ ] Resolve works
- [ ] Silences suppress matching new alerts
