from jira_integration.models import ModuleUser


class LocalIdentity:
    def get_profile(self, user):
        if not user.is_authenticated or not user.is_active:
            return None

        return ModuleUser.objects.filter(user=user, is_active=True).first()