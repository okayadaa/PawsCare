"""Command-line demo: builds a sample owner and prints today's schedule."""

from datetime import date, time

from pawpal_system import ALL_DAYS, AvailabilityWindow, Owner, PetInfo, ToDo


def print_todays_schedule(owner: Owner) -> None:
    plan = owner.generate_day_plan(date.today())

    print("Today's Schedule")
    print(f"Date: {plan.date}")
    print(f"Owner: {owner.name}")
    print("-" * 64)

    for row in plan.display_schedule():
        print(
            f"{row['time']:>10}  |  {row['pet']:<8}  |  {row['priority']:<6}  |  "
            f"{row['task']} ({row['duration_minutes']} min)"
        )

    print("-" * 64)
    print(f"Total duration: {plan.total_duration} minutes")


def main() -> None:
    owner = Owner("Alex", AvailabilityWindow(set(ALL_DAYS), time(9, 0), time(18, 0)))

    buddy = PetInfo("Buddy", 3, "Golden Retriever", "dog")
    luna = PetInfo("Luna", 5, "Siamese", "cat")
    owner.add_pet(buddy)
    owner.add_pet(luna)

    owner.add_todo(ToDo("Morning walk", 3, 30, "09:00", buddy))
    owner.add_todo(ToDo("Feed breakfast", 2, 15, "09:30", buddy))
    owner.add_todo(ToDo("Play session", 1, 20, "12:00", luna))
    owner.add_todo(ToDo("Evening grooming", 2, 25, "17:00", luna))

    print_todays_schedule(owner)


if __name__ == "__main__":
    main()
