"""
示例：一段需要重构的遗留代码。
耦合了数据库查询、邮件发送和业务逻辑。
"""
import time


class UserManager:
    """用户管理类——职责过重，需要拆分"""

    def __init__(self, db_connection=None):
        self.db = db_connection

    def get_user(self, user_id: int) -> dict:
        """从数据库获取用户"""
        # 模拟数据库查询
        users = {
            1: {"name": "Alice", "email": "alice@example.com"},
            2: {"name": "Bob", "email": "bob@example.com"},
        }
        return users.get(user_id, {})

    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        """发送邮件（模拟）"""
        print(f"Sending email to {to_address}: {subject}")
        time.sleep(0.1)  # 模拟网络 IO
        return True

    def process_user_notification(self, user_id: int) -> bool:
        """
        处理用户通知——耦合了数据获取和邮件发送。
        需要重构为关注点分离的形式。
        """
        user = self.get_user(user_id)
        if not user:
            return False

        email = user.get("email", "")
        name = user.get("name", "User")

        subject = f"Hello, {name}!"
        body = f"Dear {name},\n\nThis is your daily notification."

        return self.send_email(email, subject, body)


def calculate_score(items: list) -> float:
    """计算分数——需要增加类型注解和文档"""
    total = 0
    for item in items:
        if item > 0:
            total += item * 2
        else:
            total += 0
    return total


def legacy_function(data: str, flag: bool) -> str:
    """一个需要重构的函数"""
    result = ""
    if flag:
        result = data.upper()
    else:
        result = data.lower()
    return result


def bloated_order_processor(
    order_id, user_id, payment_method, shipping_address, discount_code,
    gift_wrap, priority, notes
):
    """
    一个典型的"屎山"函数——参数过多、IO 和业务逻辑混杂、嵌套深。
    这个函数会被项目扫描器标记为多个问题。
    """
    import requests  # noqa: F811
    total = 0
    items = []
    # 查数据库
    print(f"Fetching order {order_id} for user {user_id}")
    # 计算折扣（3 层嵌套）
    if discount_code:
        if discount_code.startswith("VIP"):
            if user_id > 1000:
                discount = 0.3
            else:
                discount = 0.2
        else:
            if discount_code == "NEWYEAR":
                discount = 0.15
            else:
                discount = 0.05
    else:
        discount = 0.0
    # IO 操作在业务逻辑中间
    print(f"Sending confirmation to {user_id}")
    # 更多嵌套
    for item in items:
        if item.get("available", False):
            if item.get("quantity", 0) > 0:
                price = item.get("price", 0)
                if priority > 5:
                    price = price * 1.2  # 加急费
                total += price * item["quantity"]
    # 又是一个 IO
    if payment_method == "credit_card":
        print(f"Processing credit card payment...")
        if not shipping_address:
            return {"error": "No shipping address for credit card order"}
    elif payment_method == "paypal":
        print(f"Redirecting to PayPal...")
    else:
        print(f"Unknown payment method: {payment_method}")
    # 发货逻辑和邮件逻辑混在一起
    if shipping_address and gift_wrap:
        print(f"Adding gift wrap for {shipping_address}")
    # 最后的 IO
    print(f"Order {order_id} processed. Total: {total}")
    return {"order_id": order_id, "total": total, "discount": discount}
