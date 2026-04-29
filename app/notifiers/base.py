class BaseNotifier:
    """
    Base notifier interface.
    """

    name = "base"
    supports_update = False

    def send(self, channel, alert, text, event_type="notification"):
        """
        Send a notification through a channel.
        """

        raise NotImplementedError

    def update(self, channel, alert, text, delivery, event_type="resolved"):
        """
        Update a previously sent notification.
        """

        raise NotImplementedError
