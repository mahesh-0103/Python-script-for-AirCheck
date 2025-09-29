from flask import Flask, request, jsonify
import datetime

# --- 1. Basic Setup & In-Memory "Database" ---
app = Flask(__name__)
conversation_sessions = {}


# --- 2. Mock Business Logic (The Airline's Fake Systems) ---

def get_flight_options(origin, destination):
    """Simulates searching a flight database with multiple routes."""
    print(f"Searching for flights from {origin} to {destination}...")
    if origin == "Bengaluru" and destination == "Delhi":
        return [
            {"flight_id": "G9-101", "time": "18:40 IST", "fare": 12450, "family": "Saver"},
            {"flight_id": "G9-203", "time": "19:20 IST", "fare": 13100, "family": "Flexi"},
            {"flight_id": "G9-415", "time": "20:00 IST", "fare": 11980, "family": "Saver"}
        ]
    elif origin == "Mumbai" and destination == "Chennai":
        return [
            {"flight_id": "G9-555", "time": "08:00 IST", "fare": 9500, "family": "Saver"},
            {"flight_id": "G9-667", "time": "11:30 IST", "fare": 11200, "family": "Flexi"}
        ]
    return [] # Return empty list if route not found

def get_flight_status(pnr, last_name):
    """Simulates checking a flight status system with more users."""
    print(f"Checking status for PNR {pnr} ({last_name})...")
    pnr = pnr.upper()
    last_name = last_name.lower()
    
    if pnr == "ZX1AB2" and last_name == "sharma":
        return {"status": "Delayed", "details": "Flight G9 102 is delayed by 45 minutes. New departure is 18:40 IST."}
    if pnr == "CD3EF4" and last_name == "gupta":
        return {"status": "On Time", "details": "Flight G9 305 is on time for departure at 21:00 IST from Gate 14."}
    if pnr == "GH5IJ6" and last_name == "patel":
        return {"status": "Cancelled", "details": "Flight G9 808 has been cancelled due to operational reasons."}
        
    return None # PNR not found

def calculate_cancellation_fee(pnr, last_name):
    """Simulates the fare rules engine with more scenarios."""
    print(f"Calculating cancellation for PNR {pnr} ({last_name})...")
    pnr = pnr.upper()
    last_name = last_name.lower()

    if pnr == "AB7YZ8" and last_name == "verma": # Saver Fare
        return {"fee": 2000, "refund": 10450, "family": "Saver"}
    if pnr == "PQ9RS0" and last_name == "iyer": # Flexi Fare
        return {"fee": 500, "refund": 12600, "family": "Flexi"}
    if pnr == "UV2WX3" and last_name == "khan": # Non-refundable
        return {"fee": 8000, "refund": 0, "family": "Non-Refundable"}
        
    return None # PNR not found


# --- 3. The Main Webhook (The Agent's "Brain") ---

@app.route('/agent_webhook', methods=['POST'])
def agent_webhook():
    request_data = request.get_json()
    session_id = request_data.get('session_id', 'default_session')
    user_input = request_data.get('user_input', '').lower()
    current_session = conversation_sessions.get(session_id, {})
    response_text = ""

    # --- PRIMARY INTENT ROUTER ---
    if not current_session.get("intent"):
        if "cancel" in user_input or "cancellation" in user_input:
            current_session = {"intent": "cancel_booking", "state": "awaiting_pnr_for_cancel"}
            response_text = "Okay, I can assist with a cancellation. Please tell me the PNR for the booking."
        elif "status" in user_input or "check" in user_input:
            current_session = {"intent": "check_status", "state": "awaiting_pnr_for_status"}
            response_text = "Sure, I can check your flight status. What is your PNR?"
        elif "book" in user_input or "ticket" in user_input:
            current_session = {"intent": "book_flight", "state": "awaiting_origin"}
            response_text = "Of course! I can help with a booking. Where will you be flying from?"
        else:
            response_text = "Welcome! You can ask me to book a flight, check a flight status, or cancel a booking. How can I help?"

    # --- STATE-BASED LOGIC HANDLERS ---
    # == BOOKING FLOW ==
    elif current_session.get("intent") == "book_flight":
        if current_session["state"] == "awaiting_origin":
            current_session["origin"] = request_data.get('user_input', '').title()
            current_session["state"] = "awaiting_destination"
            response_text = f"Okay, flying from {current_session['origin']}. And where are you flying to?"
        
        elif current_session["state"] == "awaiting_destination":
            current_session["destination"] = request_data.get('user_input', '').title()
            flights = get_flight_options(current_session["origin"], current_session["destination"])
            if flights:
                flight_options_text = ". ".join([f"Flight {f['flight_id']} departing at {f['time']} for INR {f['fare']}" for f in flights])
                response_text = f"I found a few options: {flight_options_text}. Please tell me the flight ID you'd like to book."
                current_session["state"] = "awaiting_flight_selection"
            else:
                response_text = f"I'm sorry, I couldn't find any flights from {current_session['origin']} to {current_session['destination']}. Would you like to try a different route?"
                current_session["state"] = "awaiting_origin" # Go back to asking for origin
            
        elif current_session["state"] == "awaiting_flight_selection":
            current_session["selected_flight"] = user_input.upper()
            response_text = f"Great, you've selected {current_session['selected_flight']}. Your mock PNR is {session_id[:6].upper()}. A confirmation will be sent to your email. Can I help with anything else?"
            current_session = {} # Reset session

    # == STATUS FLOW ==
    elif current_session.get("intent") == "check_status":
        if current_session["state"] == "awaiting_pnr_for_status":
            current_session["pnr"] = user_input
            current_session["state"] = "awaiting_lastname_for_status"
            response_text = "Thank you. And what is the last name on the booking?"
        elif current_session["state"] == "awaiting_lastname_for_status":
            current_session["last_name"] = user_input
            status_info = get_flight_status(current_session["pnr"], current_session["last_name"])
            if status_info:
                last_updated = datetime.datetime.now().strftime("%H:%M IST on %d %B")
                response_text = f"I found the booking. {status_info['details']}. Last updated at {last_updated}. Would you like me to send an SMS alert?"
            else:
                response_text = "I'm sorry, I couldn't find a booking with that PNR and last name. Please check the details and try again."
            current_session = {}

    # == CANCELLATION FLOW ==
    elif current_session.get("intent") == "cancel_booking":
        if current_session["state"] == "awaiting_pnr_for_cancel":
            current_session["pnr"] = user_input
            current_session["state"] = "awaiting_lastname_for_cancel"
            response_text = "Got it. And what is the last name for this booking?"
        elif current_session["state"] == "awaiting_lastname_for_cancel":
            current_session["last_name"] = user_input
            cancellation_info = calculate_cancellation_fee(current_session["pnr"], current_session["last_name"])
            if cancellation_info:
                fee, refund, family = cancellation_info['fee'], cancellation_info['refund'], cancellation_info['family']
                response_text = f"I found the booking. The fare is a {family} fare. The cancellation fee is INR {fee}. Your total refund amount will be INR {refund}. Do you want to proceed with the cancellation?"
                current_session["state"] = "awaiting_cancel_confirmation"
            else:
                response_text = "Sorry, I was unable to find that booking. Could you please double-check the PNR and last name?"
                current_session = {}
        elif current_session["state"] == "awaiting_cancel_confirmation":
            if "yes" in user_input or "proceed" in user_input:
                response_text = "Your cancellation is confirmed. The refund will be processed to your original payment method. Is there anything else I can assist with?"
            else:
                response_text = "Okay, I have not cancelled your booking. Can I help with anything else?"
            current_session = {}

    # Save the updated session state
    conversation_sessions[session_id] = current_session
    return jsonify({"response_text": response_text})


# --- 4. The Runner ---
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)