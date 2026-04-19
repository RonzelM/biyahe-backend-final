from pathlib import Path

import joblib
from flask import Blueprint, jsonify, request

maintenance_bp = Blueprint("maintenance", __name__)

MODEL_PATH = (
    Path(__file__).resolve().parent / "linear" / "linear_regression_maintenance_model.joblib"
)

try:
    maintenance_model = joblib.load(MODEL_PATH)
except Exception:
    maintenance_model = None

MAINTENANCE_FEATURES = [
    "Mileage",
    "Maintenance_History_Good",
    "Maintenance_History_Poor",
    "Transmission_Type_Manual",
    "Vehicle_Model_Car",
    "Vehicle_Model_Motorcycle",
    "Vehicle_Model_SUV",
    "Vehicle_Model_Truck",
    "Vehicle_Model_Van",
]


def _row_from_named_payload(payload):
    missing = [feature for feature in MAINTENANCE_FEATURES if feature not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    return [float(payload[feature]) for feature in MAINTENANCE_FEATURES]


@maintenance_bp.route("/predict-maintenance", methods=["POST"])
def predict_maintenance():
    if maintenance_model is None:
        return jsonify({"error": "Maintenance model failed to load"}), 500

    data = request.get_json(silent=True) or {}

    if "instances" in data and isinstance(data["instances"], list):
        instances = data["instances"]
    elif all(feature in data for feature in MAINTENANCE_FEATURES):
        instances = [data]
    elif "features" in data:
        instances = [data["features"]]
    else:
        return (
            jsonify(
                {
                    "error": "Provide named maintenance fields, or 'features', or 'instances'"
                }
            ),
            400,
        )

    if not isinstance(instances, list) or not instances:
        return jsonify({"error": "'instances' must be a non-empty list"}), 400

    try:
        cleaned = []
        for row in instances:
            if isinstance(row, dict):
                cleaned.append(_row_from_named_payload(row))
            elif isinstance(row, list) and row:
                cleaned.append([float(value) for value in row])
            else:
                return jsonify({"error": "Each instance must be a dict or non-empty list"}), 400

        preds = maintenance_model.predict(cleaned).tolist()
    except Exception as exc:
        return jsonify({"error": f"Prediction failed: {str(exc)}"}), 400

    return jsonify({"predictions": preds}), 200
