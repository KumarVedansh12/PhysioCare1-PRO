def portal_context(request):
    unread_count = 0
    if request.user.is_authenticated:
        unread_count = request.user.portal_notifications.filter(is_read=False).count()
    return {"unread_count": unread_count}
