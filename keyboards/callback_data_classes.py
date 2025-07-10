from aiogram.filters.callback_data import CallbackData


class MenuCallbackFactory(CallbackData, prefix="test"):
    path_id: int


class AdminMenuEditCallbackFactory(CallbackData, prefix="admin_edit"):
    path_id: int
    button: str


class AdminMoveMenuCallbackFactory(CallbackData, prefix='move_menu'):
    path_id: int
    path_id_move: int
    direction: str # up/down


class AdminCommandCallbackFactory(CallbackData, prefix='admin_command'):
    command: str
    params: str


class AdminDeleteCallbackFactory(CallbackData, prefix='delete_admin'):
    user_id: int


class AdminFillWallet(CallbackData, prefix='fill_amount_wallet'):
    amount: int


class SettingsBot(CallbackData, prefix='get_settings'):
    settings_name: str


class SubscriptionsBot(CallbackData, prefix='subscription'):
    subscription: bool


class SubscriptionsItemBot(CallbackData, prefix='subscription'):
    subscription: bool
    path_id: int