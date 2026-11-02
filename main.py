
# PARKING GARAGE BILLING SYSTEM

total_slots = 50
vehicles = {}
monthly_passes = []

while True:

    print("\n================================")
    print("    PARKING GARAGE BILLING SYSTEM")
    print("================================")

    print("1. Vehicle Entry")
    print("2. Vehicle Exit")
    print("3. Calculate Parking Fee")
    print("4. Monthly Pass")
    print("5. EV Parking")
    print("6. Parking Slot Availability")
    print("7. Exit")

    choice = input("\nEnter your choice (1-7): ")

    # OPTION 1: VEHICLE ENTRY
    if choice == "1":

        print("\n--- VEHICLE ENTRY ---")

        if len(vehicles) >= total_slots:
            print("Parking Garage is FULL!")

        else:
            vehicle_number = input("Enter vehicle number: ").upper()

            if vehicle_number in vehicles:
                print("Vehicle is already parked!")

            else:
                vehicle_type = input("Enter vehicle type (Car/Bike): ")

                vehicles[vehicle_number] = vehicle_type

                print("\nVehicle Entry Successful!")
                print("Vehicle Number:", vehicle_number)
                print("Vehicle Type:", vehicle_type)

    # OPTION 2: VEHICLE EXIT
    elif choice == "2":

        print("\n--- VEHICLE EXIT ---")

        vehicle_number = input("Enter vehicle number: ").upper()

        if vehicle_number in vehicles:
            vehicles.pop(vehicle_number)
            print("Vehicle Exit Successful!")

        else:
            print("Vehicle not found!")

    # OPTION 3: CALCULATE PARKING FEE
    elif choice == "3":

        print("\n--- CALCULATE PARKING FEE ---")

        vehicle_type = input("Enter vehicle type (Car/Bike): ").lower()
        hours = float(input("Enter parking hours: "))

        if hours < 0:
            print("Invalid parking hours!")

        elif vehicle_type == "car":
            fee = hours * 30
            print("Parking Fee: Rs.", fee)

        elif vehicle_type == "bike":
            fee = hours * 15
            print("Parking Fee: Rs.", fee)

        else:
            print("Invalid vehicle type!")

    # OPTION 4: MONTHLY PASS
    elif choice == "4":

        print("\n--- MONTHLY PASS ---")

        name = input("Enter customer name: ")
        vehicle_number = input("Enter vehicle number: ").upper()

        monthly_passes.append({
            "name": name,
            "vehicle": vehicle_number
        })

        print("Monthly Pass Registered Successfully!")
        print("Customer Name:", name)
        print("Vehicle Number:", vehicle_number)

    # OPTION 5: EV PARKING
    elif choice == "5":

        print("\n--- EV PARKING ---")

        vehicle_number = input("Enter EV vehicle number: ").upper()

        if vehicle_number in vehicles:
            print("Vehicle is already registered in parking!")

        elif len(vehicles) >= total_slots:
            print("Parking Garage is FULL!")

        else:
            vehicles[vehicle_number] = "EV"

            print("EV Parking Successful!")
            print("Please proceed to the EV charging station.")

    # OPTION 6: PARKING SLOT AVAILABILITY
    elif choice == "6":

        print("\n--- PARKING SLOT AVAILABILITY ---")

        occupied_slots = len(vehicles)
        available_slots = total_slots - occupied_slots

        print("Total Parking Slots:", total_slots)
        print("Occupied Slots:", occupied_slots)
        print("Available Slots:", available_slots)

    # OPTION 7: EXIT
    elif choice == "7":

        print("\nThank you for using our Parking Garage!")
        break

    # INVALID CHOICE
    else:

        print("Invalid choice! Please enter 1 to 7.")
