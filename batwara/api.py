import frappe

from batwara.utils import get_twilio_client


@frappe.whitelist()
def get_summary_for_session_user():
	user = frappe.session.user
	return get_summary_for_user(user)


def get_summary_for_user(user: str) -> list:
	owed_to_user = frappe.get_all(
		"Split Ledger Entry",
		fields=[
			"SUM(amount) AS amount",
			"credit_user",
			"currency",
		],  # assuming all transactions in same currency
		filters={"debit_user": user},
		group_by="credit_user",
	)
	owed_to_user_dict = {}
	for record in owed_to_user:
		owed_to_user_dict[record["credit_user"]] = {
			"amount": record["amount"],
			"currency": record["currency"],
		}

	user_owes = frappe.get_all(
		"Split Ledger Entry",
		fields=[
			"SUM(amount) AS amount",
			"debit_user",
			"currency",
		],  # assuming all transactions in same currency
		filters={"credit_user": user},
		group_by="debit_user",
	)
	user_owes_dict = {}
	for record in user_owes:
		user_owes_dict[record["debit_user"]] = {
			"amount": record["amount"],
			"currency": record["currency"],
		}

	unique_friends = set(owed_to_user_dict.keys()).union(set(user_owes_dict.keys()))

	summary = {}
	for friend in unique_friends:
		if friend in owed_to_user_dict and friend in user_owes_dict:
			owed_to_user = owed_to_user_dict[friend]["amount"] - user_owes_dict[friend]["amount"]

			if owed_to_user < 0:
				summary[friend] = {"net_amount": -owed_to_user, "type": "to_send"}
			elif owed_to_user > 0:
				summary[friend] = {"net_amount": owed_to_user, "type": "to_receive"}
			else:
				summary[friend] = {"net_amount": owed_to_user, "type": "even"}
		elif friend in owed_to_user_dict:
			amount = owed_to_user_dict[friend]["amount"]
			summary[friend] = {"net_amount": amount, "type": "to_receive"}
		else:
			amount = user_owes_dict[friend]["amount"]
			summary[friend] = {"net_amount": amount, "type": "to_send"}

	for friend in summary:
		summary[friend]["full_name"] = frappe.db.get_value("User", friend, "full_name")

	return summary




@frappe.whitelist(allow_guest=True)
def send_otp(phone: str):
	if frappe.conf.developer_mode:
		frappe.cache.set_value("twilio_fake_otp", "123456")
		return

	client = get_twilio_client()
	service_id = frappe.db.get_single_value("Batwara Settings", "twilio_service_id")
	client.verify.v2.services(service_id).verifications.create(to=phone, channel="sms")


@frappe.whitelist(allow_guest=True)
def verify_otp_and_login(phone: str, otp: str, invite_code=None):
	verify_otp(phone, otp)
	login_user_with_phone(phone)

	if invite_code:
		add_friend(phone, invite_code)

def add_friend(phone: str, invite_code: str):
	if not frappe.db.exists("Friend Invitation", invite_code):
		return

	invited_by = frappe.db.get_value("Friend Invitation", invite_code, "invited_by")
	friend = get_user_name_with_phone(phone)

	frappe.get_doc({
		"doctype": "Friend Mapping",
		"a": invited_by,
		"b": friend
	}).insert(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
def verify_otp_and_register(email: str, full_name: str, phone: str, otp: str):
	verify_otp(phone, otp)
	create_user_and_login(email, full_name, phone)


def create_user_and_login(email, first_name, phone):
	frappe.get_doc({
		"doctype": "User",
		"email": email,
		"mobile_no": phone,
		"first_name": first_name
	}).insert(ignore_permissions=True)
	login_user_with_phone(phone)


def verify_otp(phone: str, otp: str):
	if frappe.conf.developer_mode:
		if frappe.cache.get_value("twilio_fake_otp") == otp:
			return
		else:
			frappe.throw("Incorrect OTP!")

	client = get_twilio_client()
	service_id = frappe.db.get_single_value("Batwara Settings", "twilio_service_id")

	verification_check = client.verify.v2.services(service_id).verification_checks.create(to=phone, code=otp)

	if verification_check.status != "approved":
		frappe.throw("Incorrect OTP!")


def login_user_with_phone(phone: str):
	user = get_user_name_with_phone(phone)

	# login the user
	from frappe.auth import LoginManager

	login_manager = LoginManager()
	login_manager.login_as(user)


def get_user_name_with_phone(phone: str):
	# find the user to which this phone number belongs to
	user_exists = frappe.db.exists("User", {"mobile_no": phone})

	if not user_exists:
		frappe.throw("Phone number not registered!")

	return frappe.db.get_value("User", {"mobile_no": phone}, "name")

