from flask import Flask, render_template, request, jsonify
from auth import Auth
from api import LocketAPI
import json
import time
import requests

app = Flask(__name__)

# Initialize API and Auth
subscription_ids = [
    "locket_1600_1y",
    "locket_199_1m",
    "locket_199_1m_only",
    "locket_3600_1y",
    "locket_399_1m_only",
    "",
]
auth = Auth("locket@maihuybao.dev", "Mhbao@26062007")
try:
    token = auth.get_token()
    api = LocketAPI(token)
except Exception as e:
    print(f"Error initializing API: {e}")
    api = None


def refresh_api_token():
    global api
    try:
        print("Refreshing API token...")
        new_token = auth.create_token()
        api = LocketAPI(new_token)
        print("API token refreshed successfully.")
        return True
    except Exception as e:
        print(f"Failed to refresh API token: {e}")
        return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/get-user-info", methods=["POST"])
def get_user_info():
    if not api:
        return jsonify(
            {"success": False, "msg": "API not initialized. Check server logs."}
        ), 500

    data = request.json
    username = data.get("username")

    if not username:
        return jsonify({"success": False, "msg": "Username is required"}), 400

    try:
        # User lookup
        print(f"Looking up user: {username}")
        try:
            account_info = api.getUserByUsername(username)
        except Exception as e:
            if "401" in str(e) or "Unauthenticated" in str(e):
                print(f"Creating new token because of {e}")
                if refresh_api_token():
                    account_info = api.getUserByUsername(username)
                else:
                    raise e
            else:
                raise e

        # Check if we got a valid response structure
        if not account_info or "result" not in account_info:
            return jsonify(
                {"success": False, "msg": "User not found or API error"}
            ), 404

        user_data = account_info.get("result", {}).get("data")
        if not user_data:
            return jsonify({"success": False, "msg": "User data not found"}), 404

        # Extract relevant user information
        user_info = {
            "uid": user_data.get("uid"),
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "profile_picture_url": user_data.get("profile_picture_url", ""),
        }

        return jsonify({"success": True, "data": user_info})

    except Exception as e:
        print(f"Error in get user info: {e}")
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500


def send_telegram_notification(username, uid, product_id, raw_json):
    bot_token = (
        "8529598333:AAGl46FejTf7rU9_yCBgOh3ZWAPgeVmrGkA"  # Replace with your bot token
    )
    chat_id = "5267646360"  # Replace with your chat ID

    if bot_token == "YOUR_BOT_TOKEN" or chat_id == "YOUR_CHAT_ID":
        print("Telegram notification skipped: Token or Chat ID not set.")
        return
    subscription_info = json.dumps(
        raw_json.get("subscriber", {}).get("entitlements", {}).get("Gold", {}), indent=2
    )

    message = f"✅ <b>Locket Gold Unlocked!</b>\n\n👤 <b>User:</b> {username} ({uid})\n⏰ <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n<b>Subscription Info:</b>\n<pre>{subscription_info}</pre>"
    # send file json
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")


@app.route("/api/restore", methods=["POST"])
def restore_purchase():
    if not api:
        return jsonify(
            {"success": False, "msg": "API not initialized. Check server logs."}
        ), 500

    data = request.json
    username = data.get("username")

    if not username:
        return jsonify({"success": False, "msg": "Username is required"}), 400

    try:
        # User lookup
        print(f"Looking up user: {username}")
        try:
            account_info = api.getUserByUsername(username)
        except Exception as e:
            if "401" in str(e) or "Unauthenticated" in str(e):
                print(f"Creating new token because of {e}")
                if refresh_api_token():
                    account_info = api.getUserByUsername(username)
                else:
                    raise e
            else:
                raise e
        # Check if we got a valid response structure
        if not account_info or "result" not in account_info:
            return jsonify(
                {"success": False, "msg": "User not found or API error"}
            ), 404

        user_data = account_info.get("result", {}).get("data")
        if not user_data:
            return jsonify({"success": False, "msg": "User data not found"}), 404

        uid_target = user_data.get("uid")
        if not uid_target:
            return jsonify({"success": False, "msg": "UID not found for user"}), 404

        print(f"Restoring purchase for UID: {uid_target}")
        # Restore purchase
        try:
            restore_result = api.restorePurchase(uid_target)
        except Exception as e:
            if "401" in str(e) or "Unauthenticated" in str(e):
                print(f"Creating new token because of {e}")
                if refresh_api_token():
                    restore_result = api.restorePurchase(uid_target)
                else:
                    raise e
            else:
                raise e

        # Check entitlement
        entitlements = restore_result.get("subscriber", {}).get("entitlements", {})
        gold_entitlement = entitlements.get("Gold", {})

        if gold_entitlement.get("product_identifier") in subscription_ids:
            # Send Telegram notification
            send_telegram_notification(
                username,
                uid_target,
                gold_entitlement.get("product_identifier"),
                restore_result,
            )

            return jsonify(
                {
                    "success": True,
                    "msg": f"Purchase {gold_entitlement.get('product_identifier')} for {username} successfully!",
                }
            )
        else:
            return jsonify(
                {
                    "success": False,
                    "msg": f"Restore purchase failed. Gold entitlement not found for {username}.",
                }
            )

    except Exception as e:
        print(f"Error in restore process: {e}")
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=8000)
