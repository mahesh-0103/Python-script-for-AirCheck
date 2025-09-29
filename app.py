from flask import Flask, request, jsonify
import datetime
import json
import pytz

# --- 1. Basic Setup & Loading Data from JSON Files ---
app = Flask(__name__)
try:
    with open('bookings.json', 'r') as f:
        bookings_db = json.load(f)
    with open('flights.json', 'r') as f:
        flights_db = json.load(f)
except FileNotFoundError:
    print("ERROR: Make sure bookings.json and flights.json are in the same directory.")
    exit()
conversation_sessions = {}

# --- 2. Helper Functions ---
def get_flight_options(origin_iata, destination_iata):
    """Looks up flight schedules from the flights_db."""
    route_key = f"{origin_iata.upper()}-{destination_iata.upper()}"
    return flights_db.get(route_key, [])

def get_booking_details(pnr, last_name):
    """
    Looks up a booking in the bookings_db.
    Returns a tuple: (booking_object, reason_code).
    Reason codes: 'success', 'pnr_not_found', 'name_mismatch'.
    """
    pnr = pnr.upper()
    booking = bookings_db.get(pnr)
    if not booking:
        return (None, 'pnr_not_found')
    if booking.get('last_name').lower() != last_name.lower():
        return (None, 'name_mismatch')
    return (booking, 'success')

def calculate_cancellation_fee(booking):
    """Applies a time-based cancellation fee rules engine to a booking object."""
    now_utc = datetime.datetime.now(pytz.utc)
    depart_time_str = booking.get('departure_timestamp_utc')
    if not depart_time_str: return None
    
    depart_time_utc = datetime.datetime.fromisoformat(depart_time_str.replace('Z', '+00:00'))
    if depart_time_utc < now_utc:
        return {"family": booking.get('fare_family'), "fee": booking.get('total_fare'), "refund": 0}

    hours_to_departure = (depart_time_utc - now_utc).total_seconds() / 3600
    fare_family = booking.get('fare_family')
    total_fare = booking.get('total_fare')
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
    """Helper to format flight details into a readable string per hackathon guidelines."""
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

    # --- Global Intent Handling (Human Handoff) ---
    if "human" in user_input or "agent" in user_input or "person" in user_input:
        response_text = "I understand. Let me transfer you to a human agent for further assistance."
        current_session = {"intent": "agent_transfer"}
        conversation_sessions[session_id] = current_session
        return jsonify({"response_text": response_text, "intent_label": "agent_transfer"})

    # --- Primary Intent Router ---
    if not current_session.get("intent"):
        if "cancel" in user_input:
            current_session = {"intent": "cancel_booking", "state": "awaiting_pnr_for_cancel"}
            response_text = "Okay, I can assist with a cancellation. Please tell me the PNR for the booking."
        elif "status" in user_input:
            current_session = {"intent": "check_status", "state": "awaiting_pnr_for_status"}
            response_text = "Sure, I can check your flight status. What is your PNR?"
        elif "book" in user_input:
            current_session = {"intent": "book_flight", "state": "awaiting_trip_type"}
            response_text = "Of course! To start, is this a one-way or a round trip?"
        else:
            response_text = "Welcome! You can ask me to book a flight, check a flight status, or cancel a booking."

    # == BOOKING FLOW (Feature Complete) ==
    elif current_session.get("intent") == "book_flight":
        state = current_session.get("state")
        if state == "awaiting_trip_type":
            current_session["trip_type"] = user_input
            current_session["state"] = "awaiting_origin"
            response_text = "Got it. Where will you be flying from? Please provide the IATA code."
        elif state == "awaiting_origin":
            current_session["origin"] = user_input.upper()
            current_session["state"] = "awaiting_destination"
            response_text = f"From {current_session['origin']}. And where to? Please provide the IATA code."
        elif state == "awaiting_destination":
            current_session["destination"] = user_input.upper()
            current_session["state"] = "awaiting_depart_date"
            response_text = "Great. On what date?"
        elif state == "awaiting_depart_date":
            current_session["depart_date"] = user_input
            current_session["state"] = "awaiting_pax_count"
            response_text = f"Okay, on {current_session['depart_date']}. How many adults and children?"
        elif state == "awaiting_pax_count":
            current_session["pax_count"] = user_input
            current_session["state"] = "awaiting_cabin_class"
            response_text = "And which cabin class: Economy, or Business?"
        elif state == "awaiting_cabin_class":
            current_session["cabin_class"] = user_input
            current_session["state"] = "awaiting_ssr"
            response_text = "Do you have any special service requests, like a wheelchair or special meal?"
        elif state == "awaiting_ssr":
            current_session["ssr_list"] = user_input
            flights = get_flight_options(current_session["origin"], current_session["destination"])
            if flights:
                current_session["flight_options"] = flights
                response_text = f"I found a few options: {format_flight_options(flights)} You can ask for the cheapest, or nonstop, or select a flight ID."
                current_session["state"] = "awaiting_flight_selection"
            else:
                response_text = "I'm sorry, I couldn't find any flights. Would you like to try a different route?"
                current_session["state"] = "awaiting_origin"
        
        elif state == "awaiting_flight_selection":
            if "cheapest" in user_input:
                cheapest_flight = sorted(current_session["flight_options"], key=lambda x: x['fare'])[0]
                response_text = f"The cheapest option is {format_flight_options([cheapest_flight])} Would you like to select this one?"
            elif "nonstop" in user_input:
                nonstop_flights = [f for f in current_session["flight_options"] if f['layovers'] == 0]
                if nonstop_flights:
                    response_text = f"Here are the nonstop options: {format_flight_options(nonstop_flights)} Please select one."
                else:
                    response_text = "Sorry, there are no nonstop flights on this route. Here are the original options again: " + format_flight_options(current_session["flight_options"])
            else:
                current_session["selected_flight_id"] = user_input.upper()
                response_text = f"You've selected {current_session['selected_flight_id']}. Please confirm to proceed to payment."
                current_session["state"] = "awaiting_payment_confirmation"

        elif state == "awaiting_payment_confirmation":
             if "yes" in user_input or "confirm" in user_input:
                pnr = session_id[:6].upper()
                response_text = f"Payment successful. Your booking is confirmed. Your PNR is {pnr}. A confirmation has been sent to your email."
                actions.append({"type": "email", "integration_name": "AirCheck_Email_Confirmations", "to": "mock.user@example.com", "subject": f"Booking Confirmed: {pnr}"})
                current_session = {}
             else:
                response_text = "Okay, I've cancelled the booking. How else can I help?"
                current_session = {}

    # == STATUS & CANCELLATION FLOWS (With Enhancements) ==
    elif current_session.get("intent") in ["check_status", "cancel_booking"]:
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
                    response_text = f"I found the booking. The fare is a {cancellation_info['family']} fare. The fee is INR {cancellation_info['fee']}. Your refund will be INR {cancellation_info['refund']}. Do you want to proceed?"
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
            if "voucher" in user_input:
                response_text = "Your cancellation is confirmed. A travel voucher has been sent to your email."
            else:
                response_text = "Your cancellation is confirmed. The refund will be processed to your original payment method."
            current_session = {}

    conversation_sessions[session_id] = current_session
    return jsonify({"response_text": response_text, "actions": actions})

# --- 4. The Runner ---
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)
