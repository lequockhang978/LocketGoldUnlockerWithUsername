from flask import Flask, render_template, request, jsonify
from auth import Auth
from api import LocketAPI
import json

app = Flask(__name__)

# Initialize API and Auth
subscription_id = "locket_1600_1y"
auth = Auth("locket@maihuybao.dev", "Mhbao@26062007")
try:
    token = auth.get_token()
    api = LocketAPI(token)
except Exception as e:
    print(f"Error initializing API: {e}")
    api = None


@app.route("/")
def index():
    return render_template("index.html")


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
        account_info = api.getUserByUsername(username)
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
        restore_result = api.restorePurchase(uid_target)

        # Check entitlement
        entitlements = restore_result.get("subscriber", {}).get("entitlements", {})
        gold_entitlement = entitlements.get("Gold", {})

        if gold_entitlement.get("product_identifier") == subscription_id:
            return jsonify({"success": True, "msg": f"Purchase {subscription_id} for {username} successfully!"})
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
