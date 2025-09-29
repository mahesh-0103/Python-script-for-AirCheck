from flask import Flask, request, jsonify
import datetime
import pytz

# --- 1. Basic Setup & Embedded Mock Data ---
app = Flask(__name__)

# NEW: Added a city name to IATA code lookup dictionary
city_to_iata = {
    "bengaluru": "BLR", "bangalore": "BLR",
    "delhi": "DEL",
    "mumbai": "BOM", "bombay": "BOM",
    "chennai": "MAA", "madras": "MAA",
    "kolkata": "CCU", "calcutta": "CCU"
}

flights_db = {
  "BLR-DEL": [
    { "flight_id": "G9-101", "time": "18:40 IST", "duration": "2h 30m", "layovers": 0, "fare": 12450, "family": "Saver", "baggage_allowance": "15kg Checked" },
    { "flight_id": "G9-203", "time": "19:20 IST", "duration": "2h 35m", "layovers": 0, "fare": 13100, "family": "Flexi", "baggage_allowance": "25kg Checked" },
    { "flight_id": "G9-415", "time": "20:00 IST", "duration": "3h 15m", "layovers": 1, "fare": 11980, "family": "Saver", "baggage_allowance": "15kg Checked" }
  ],
  "BOM-MAA": [
    { "flight_id": "G9-555", "time": "08:00 IST", "duration": "1h 45m", "layovers": 0, "fare": 9500, "family": "Saver", "baggage_allowance": "15kg Checked" },
    { "flight_id": "G9-667", "time": "11:30 IST", "duration": "1h 50m", "layovers": 0, "fare": 11200, "family": "Flexi", "baggage_allowance": "25kg Checked" }
  ]
}

bookings_db = {
  "ZX1AB2": { "last_name": "Sharma", "flight_id": "G9 102", "departure_timestamp_utc": "2025-10-02T13:10:00Z", "status": "Delayed", "status_details": "Flight G9 102 is delayed by 45 minutes. New departure is 18:40 IST.", "passengers": ["Anjali Sharma"], "ssr_list": [] },
  "CD3EF4": { "last_name": "Gupta", "flight_id": "G9 305", "departure_timestamp_utc": "2025-09-30T15:30:00Z", "status": "On Time", "status_details": "Flight G9 305 is on time for departure at 21:00 IST from Gate 14.", "passengers": ["Rohan Gupta"], "ssr_list": [] },
  "GH5IJ6": { "last_name": "Patel", "flight_id": "G9 808", "departure_timestamp_utc": "2025-10-05T18:30:00Z", "status": "Cancelled", "status_details": "Flight G9 808 has been cancelled due to operational reasons.", "passengers": ["Priya Patel", "Aarav Patel"], "ssr_list": [] },
  "AB7YZ8": { "last_name": "Verma", "flight_id": "G9-415", "departure_timestamp_utc": "2025-10-04T09:00:00Z", "fare_family": "Saver", "total_fare": 12450, "passengers": ["Sanjay Verma"], "ssr_list": ["Wheelchair assistance"] },
  "PQ9RS0": { "last_name": "Iyer", "flight_id": "G9-667", "departure_timestamp_utc": "2025-10-01T06:00:00Z", "fare_family": "Flexi", "total_fare": 13100, "passengers": ["Meera Iyer"], "ssr_list": [] },
  "UV2WX3": { "last_name": "Khan", "flight_id": "G9-101", "departure_timestamp_utc": "2025-09-30T19:00:00Z", "fare_family": "Non-Refundable", "total_fare": 8000, "passengers": ["Fatima Khan"], "ssr_list": [] }
}

conversation_sessions = {}

# --- 2. Helper Functions ---
def parse_location(location_str):
    """Converts city names or codes to a standard IATA code."""
    location_str = location_str.lower().strip()
    return city_to_iata.get(location_str, location_str.upper())

def get_flight_options(origin_iata, destination_iata):
    route_key = f"{origin_iata}-{destination_iata}"
    return flights_db.get(route_key, [])

def get_booking_details(pnr, last_name):
    pnr = pnr.upper()
    booking = bookings_db.get(pnr)
    if not booking: return (None, 'pnr_not_found')
    if booking.get('last_name').lower() != last_name.lower(): return (None, 'name_mismatch')
    return (booking, 'success')

def calculate_cancellation_fee(booking):
    now_utc = datetime.datetime.now(pytz.utc)
    depart_time_str = booking.get('departure_timestamp_utc')
    if not depart_time_str: return None
    
    depart_time_utc = datetime.datetime.fromisoformat(depart_time_str.replace('Z', '+00:00'))
    if depart_time_utc < now_utc: return {"family": booking.get('fare_family'), "fee": booking.get('total_fare'), "refund": 0}

    hours_to_departure = (depart_time_utc - now_utc).total_seconds() / 3600
    fare_family, total_fare = booking.get('fare_family'), booking.get('total_fare')
    fee = total_fare

    if fare_family == 'Flexi':
        if hours_to_departure > 72: fee = 500
        elif 24 <= hours_to_departure <= 72: fee = 1000
        else: fee = 2500
    elif fare_family == 'Saver':
        if hours_to_departure > 72: fee = 2000
        elif 24 <= hours_to_departure <= 72: fee = 3000
        else: fee = 5000

    refund = max(0, total_fare - fee)
    return {"family": fare_family, "fee": fee, "refund": refund}

def format_flight_options(flights):
    options = []
    for f in flights:
        layover_text = "nonstop" if f['layovers'] == 0 else f"{f['layovers']} layover"
        options.append(f"Flight {f['flight_id']} departing at {f['time']} is a {layover_text} flight with a duration of {f['duration']}. The fare is INR {f['fare']}.")
    return " ".join(options)

# --- 3. The Main Webhook (The Agent's "Brain") ---
@app.route('/agent_webhook', methods=['POST'])
def agent_webhook():
    request_data = request.get_json()
    session_id = request_data.get('session_id', 'default_session')
    user_input = request_data.get('user_input', '').lower()
    current_session = conversation_sessions.get(session_id, {})
    response_text = ""
    actions = []

    if "human" in user_input or "agent" in user_input:
        response_text = "I understand. Let me transfer you to a human agent."
        current_session = {"intent": "agent_transfer"}
        conversation_sessions[session_id] = current_session
        return jsonify({"response_text": response_text, "intent_label": "agent_transfer"})

    if not current_session.get("intent"):
        if "cancel" in user_input:
            current_session = {"intent": "cancel_booking", "state": "awaiting_pnr_for_cancel"}
            response_text = "Okay, I can assist with a cancellation. Please tell me the PNR for the booking."
        elif "status" in user_input:
            current_session = {"intent": "check_status", "state": "awaiting_pnr_for_status"}
            response_text = "Sure, I can check your flight status. What is your PNR?"
        elif "book" in user_input:
            current_session["intent"] = "book_flight"
            # NEW: Smart slot filling for one-shot requests
            words = user_input.split()
            try:
                if "from" in words:
                    from_index = words.index("from")
                    current_session["origin"] = parse_location(words[from_index + 1])
                if "to" in words:
                    to_index = words.index("to")
                    current_session["destination"] = parse_location(words[to_index + 1])
            except (ValueError, IndexError):
                pass # Ignore if parsing fails, will ask user for info anyway

            if not current_session.get("origin"):
                current_session["state"] = "awaiting_origin"
                response_text = "Of course! Where will you be flying from?"
            elif not current_session.get("destination"):
                 current_session["state"] = "awaiting_destination"
                 response_text = f"Okay, flying from {current_session['origin']}. And where to?"
            else:
                 current_session["state"] = "awaiting_trip_type"
                 response_text = f"Got it, booking from {current_session['origin']} to {current_session['destination']}. Is this a one-way or a round trip?"
        else:
            response_text = "Welcome! You can ask me to book a flight, check a flight status, or cancel a booking."

    elif current_session.get("intent") == "book_flight":
        state = current_session.get("state")
        if state == "awaiting_origin":
            current_session["origin"] = parse_location(user_input)
            current_session["state"] = "awaiting_destination"
            response_text = f"From {current_session['origin']}. And where to?"
        elif state == "awaiting_destination":
            current_session["destination"] = parse_location(user_input)
            current_session["state"] = "awaiting_trip_type"
            response_text = f"Got it, from {current_session['origin']} to {current_session['destination']}. Is this a one-way or a round trip?"
        elif state == "awaiting_trip_type":
            current_session["trip_type"] = user_input
            current_session["state"] = "awaiting_depart_date"
            response_text = "Okay. On what date?"
        elif state == "awaiting_depart_date":
            current_session["depart_date"] = user_input
            current_session["state"] = "awaiting_pax_count"
            response_text = f"On {current_session['depart_date']}. How many passengers in total?"
        elif state == "awaiting_pax_count":
            current_session["pax_count"] = user_input
            current_session["state"] = "awaiting_cabin_class"
            response_text = "And which cabin class: Economy, or Business?"
        elif state == "awaiting_cabin_class":
            current_session["cabin_class"] = user_input
            current_session["state"] = "awaiting_ssr"
            response_text = "Do you have any special service requests, like a wheelchair?"
        elif state == "awaiting_ssr":
            current_session["ssr_list"] = user_input
            flights = get_flight_options(current_session["origin"], current_session["destination"])
            if flights:
                current_session["flight_options"] = flights
                response_text = f"I found a few options: {format_flight_options(flights)} You can ask for the cheapest, or select a flight ID."
                current_session["state"] = "awaiting_flight_selection"
            else:
                response_text = "I'm sorry, I couldn't find any flights. Would you like to try again?"
                current_session = {}
        elif state == "awaiting_flight_selection":
            if "cheapest" in user_input:
                cheapest_flight = sorted(current_session["flight_options"], key=lambda x: x['fare'])[0]
                response_text = f"The cheapest is {format_flight_options([cheapest_flight])} Select this one?"
            else:
                current_session["selected_flight_id"] = user_input.upper()
                response_text = f"You've selected {current_session['selected_flight_id']}. Please confirm to proceed to payment."
                current_session["state"] = "awaiting_payment_confirmation"
        elif state == "awaiting_payment_confirmation":
             if "yes" in user_input or "confirm" in user_input:
                pnr = session_id[:6].upper()
                response_text = f"Payment successful. Your booking is confirmed. Your PNR is {pnr}."
                actions.append({"type": "email", "integration_name": "AirCheck_Email_Confirmations", "to": "mock.user@example.com", "subject": f"Booking Confirmed: {pnr}"})
                current_session = {}
             else:
                response_text = "Okay, I've cancelled the booking."
                current_session = {}

    elif current_session.get("intent") in ["check_status", "cancel_booking"]:
        # (This part of the code is already robust and doesn't need changes)
        state = current_session.get("state")
        if state in ["awaiting_pnr_for_status", "awaiting_pnr_for_cancel"]:
            current_session["pnr"] = user_input
            current_session["state"] = "awaiting_lastname"
            response_text = "Thank you. And what is the last name on the booking?"
        elif state == "awaiting_lastname":
            current_session["last_name"] = user_input
            booking, reason = get_booking_details(current_session["pnr"], current_session["last_name"])
            if reason == 'success':
                if current_session.get("intent") == "check_status":
                    last_updated = datetime.datetime.now().strftime("%H:%M IST")
                    response_text = f"I found the booking. {booking['status_details']}. Last updated at {last_updated}."
                    actions.append({"type": "sms", "integration_name": "AirCheck_SMS_Alerts", "to": "+910000000000", "message": f"Flight Status: {booking['status_details']}"})
                    if booking['status'] == 'Cancelled':
                        response_text += " Would you like me to help you find a new flight?"
                        current_session = {"intent": "book_flight", "state": "awaiting_origin"}
                    else:
                        current_session = {}
                else:
                    cancellation_info = calculate_cancellation_fee(booking)
                    response_text = f"I found the booking. The fare is a {cancellation_info['family']} fare. The fee is INR {cancellation_info['fee']}. Your refund is INR {cancellation_info['refund']}. Do you want to proceed?"
                    current_session["state"] = "awaiting_cancel_confirmation"
            else:
                if reason == 'pnr_not_found': response_text = "I'm sorry, I couldn't find a booking with that PNR."
                elif reason == 'name_mismatch': response_text = "I found the PNR, but the last name does not match."
                current_session = {}
        elif state == "awaiting_cancel_confirmation":
            if "yes" in user_input:
                current_session["state"] = "awaiting_refund_choice"
                response_text = "Okay. Would you like the refund sent to your original payment method, or would you prefer a travel voucher?"
            else:
                response_text = "Okay, I have not cancelled your booking."
                current_session = {}
        elif state == "awaiting_refund_choice":
            if "voucher" in user_input: response_text = "Your cancellation is confirmed. A travel voucher has been sent to your email."
            else: response_text = "Your cancellation is confirmed. The refund will be processed to your original payment method."
            current_session = {}

    conversation_sessions[session_id] = current_session
    return jsonify({"response_text": response_text, "actions": actions})

# --- 4. The Runner ---
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)
