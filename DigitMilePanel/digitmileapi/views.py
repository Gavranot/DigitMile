# myapi/views.py
from rest_framework import generics  # For ListAPIView
from .serializers import ClassroomBasicSerializer  # To serialize classroom data
from .serializers import SchoolSerializer  # Ensure SchoolSerializer is imported
from .serializers import (
    RunStatisticsSerializer,
)  # Ensure RunStatisticsSerializer is imported
from rest_framework import viewsets, permissions
from rest_framework.authentication import (
    SessionAuthentication,
)  # Add this to be explicit
from rest_framework.throttling import AnonRateThrottle
from .serializers import TeacherStudentManagementSerializer  # Add this new serializer
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse_lazy
from django.middleware.csrf import get_token
from .forms import SchoolRegistrationForm, TeacherRegistrationForm
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import (
    ClassroomWeekStats,
    Classroom,
    Student,
    StudentWeekLevelStats,
    StudentWeekStats,
    Teacher,
    School,
    RunStatistics,
    TeacherSchoolAssignment,
    Run,
    TurnEvent,
    SpecialTileTrigger,
)
from .serializers import (
    CheckClassroomResponseSerializer,
    LevelStatisticsInputSerializer,
    RunStatisticsSerializer,  # Import if you use it for creation validation/response
)
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import datetime, timezone as dt_timezone
from django.core.mail import send_mail
from django.core.cache import cache
from django.conf import settings
from django.http import JsonResponse
import logging

from .replay_archives import get_replay_payload_for_run
from .run_ingestion import (
    clamp_elapsed_ms,
    get_recording_window_status_for_run_finish,
    unix_ms_to_datetime,
)
from .run_bucket_trends import bulk_student_run_bucket_points, get_student_run_bucket_points
from .rollup_analytics import (
    back_card_usage_by_place_by_level as rollup_back_card_usage_by_place_by_level,
    bag_conditional_accuracy_by_comparator_by_level as rollup_bag_conditional_accuracy_by_comparator_by_level,
    card_accuracy_by_family_by_level as rollup_card_accuracy_by_family_by_level,
    decision_time_by_card_type as rollup_decision_time_by_card_type,
    decision_time_by_family_by_level as rollup_decision_time_by_family_by_level,
    foreach_tile_context_usage_by_level as rollup_foreach_tile_context_usage_by_level,
    mistake_hotspots_by_level as rollup_mistake_hotspots_by_level,
    number_choice_distribution_by_level as rollup_number_choice_distribution_by_level,
    number_decision_time_by_choice_by_level as rollup_number_decision_time_by_choice_by_level,
    offer_choice_share_by_family as rollup_offer_choice_share_by_family,
    special_tile_chain_length_distribution_by_level as rollup_special_tile_chain_length_distribution_by_level,
    special_tile_breakdown as rollup_special_tile_breakdown,
    time_distribution_by_level as rollup_time_distribution_by_level,
    tile_conditional_accuracy_by_tile_type_by_level as rollup_tile_conditional_accuracy_by_tile_type_by_level,
    win_rate_by_level as rollup_win_rate_by_level,
    wrong_moves_rate_by_level as rollup_wrong_moves_rate_by_level,
)

# Set up logger for email operations
logger = logging.getLogger(__name__)


def _log_run_ingest_event(level, event, **context):
    logger.log(level, "%s %s", event, context)


CARD_FAMILY_BY_TYPE = {
    "MoveX": "move",
    "IfXMoveYElseMoveZ": "conditional_tile",
    "IfBagEqualXMoveYElseMoveZ": "conditional_bag_eq",
    "IfBagLessXMoveYElseMoveZ": "conditional_bag_lt",
    "IfBagGreaterXMoveYElseMoveZ": "conditional_bag_gt",
    "BagCount": "bagcount",
    "ForXMoveY": "foreach_tile",
    "Back": "back",
}


def _normalize_card_type_for_ingestion(card_type):
    """Normalize card type names so default rules are applied consistently."""
    if not isinstance(card_type, str):
        return ""
    if card_type in {"Bug", "Back"} or card_type.startswith("AllBack"):
        return "Back"
    return card_type


def _parse_card_data_string(card_data):
    """
    Parse Unity card data payload to a canonical map of known fields.
    Example input: "[CardData: tileType=, ifSign=, ifValue=, thenValue=2, elseValue=]"
    """
    fields = {
        "tileType": "",
        "ifSign": "",
        "ifValue": "",
        "thenValue": "",
        "elseValue": "",
    }
    if not card_data:
        return fields

    raw = str(card_data).strip()
    if raw.startswith("[CardData:"):
        raw = raw[len("[CardData:") :].strip()
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]

    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key not in fields:
            continue
        fields[key] = value.strip()

    return fields


def _serialize_card_data_string(fields):
    ordered_keys = ("tileType", "ifSign", "ifValue", "thenValue", "elseValue")
    body = ", ".join(f"{key}={fields.get(key, '')}" for key in ordered_keys)
    return f"[CardData: {body}]"


def _normalize_card_payload_for_ingestion(card):
    """
    Ensure known card payload quirks are normalized before persistence.
    Critical fix: MoveX/Back cards can omit thenValue, which semantically defaults to 1.
    """
    if not isinstance(card, dict):
        return card

    normalized = dict(card)
    card_type = _normalize_card_type_for_ingestion(normalized.get("type"))

    if card_type in {"MoveX", "Back"}:
        fields = _parse_card_data_string(normalized.get("data"))
        if fields.get("thenValue", "") == "":
            fields["thenValue"] = "1"
            normalized["data"] = _serialize_card_data_string(fields)

    return normalized


def _normalize_cards_for_ingestion(chosen_card, offered_cards):
    normalized_chosen = _normalize_card_payload_for_ingestion(chosen_card)
    normalized_offered = [
        _normalize_card_payload_for_ingestion(card) for card in (offered_cards or [])
    ]
    return normalized_chosen, normalized_offered


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_card_metadata(card):
    if not isinstance(card, dict):
        return ("unknown", "unknown", None)

    card_type = _normalize_card_type_for_ingestion(card.get("type")) or "unknown"
    card_family = CARD_FAMILY_BY_TYPE.get(card_type, "unknown")
    parsed_data = _parse_card_data_string(card.get("data"))
    card_tile_type = _safe_int(parsed_data.get("tileType"))
    return (card_type, card_family, card_tile_type)


class UnsafeSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # To not perform the csrf check previously happening


class FetchCSRFTokenView(APIView):
    throttle_classes = [AnonRateThrottle]
    permission_classes = [permissions.AllowAny]

    authentication_classes = [UnsafeSessionAuthentication]

    def get(self, request, *args, **kwargs):
        token = get_token(request)
        return JsonResponse({"csrfToken": token})


class CheckStudentCredentialsView(APIView):
    """
    Checks the student's birth date to authorize the player
    """

    throttle_classes = [AnonRateThrottle]

    def post(self, request, *args, **kwargs):
        student_name_from_request = request.data.get("studentName")
        date_of_birth_from_request = request.data.get("studentBirthDate")

        if not student_name_from_request or not date_of_birth_from_request:
            return Response(
                {
                    "error": "Invalid input: either student name or date of birth are missing"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parse the date of birth (format: Year/Month/Day)
        try:
            from datetime import datetime

            # Try parsing Year/Month/Day format (e.g., "2015/03/25")
            parsed_date = datetime.strptime(
                date_of_birth_from_request, "%Y/%m/%d"
            ).date()
        except ValueError:
            try:
                # Fallback: Try YYYY-MM-DD format (e.g., "2015-03-25")
                parsed_date = datetime.strptime(
                    date_of_birth_from_request, "%Y-%m-%d"
                ).date()
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Expected YYYY/MM/DD or YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Check if student exists with matching name and date of birth
        try:
            student = Student.objects.get(
                full_name=student_name_from_request, date_of_birth=parsed_date
            )

            # Student credentials are valid
            return Response(
                {
                    "message": "Student credentials verified successfully",
                    "student_id": student.id,
                    "student_name": student.full_name,
                    "classroom": student.classroom.classroom_name,
                    "grade": student.grade,
                },
                status=status.HTTP_200_OK,
            )

        except Student.DoesNotExist:
            # Student not found with those credentials
            return Response(
                {
                    "error": "Student credentials verification failed. Student not found with the provided name and date of birth."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        except Student.MultipleObjectsReturned:
            # Multiple students found (shouldn't happen due to unique_together, but handle it)
            return Response(
                {
                    "error": "Multiple students found with those credentials. Please contact your teacher."
                },
                status=status.HTTP_409_CONFLICT,
            )


class CheckClassroomKeyView(APIView):
    """
    Checks if a classroom key exists and returns classroom, teacher, and student data.
    """

    throttle_classes = [AnonRateThrottle]

    def post(self, request, *args, **kwargs):
        classroom_key_from_request = request.data.get("classroomKey")

        if not classroom_key_from_request:
            return Response(
                {"error": "Invalid input: classroomKey missing"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Fetch the classroom using its unique classroom_key
            # select_related fetches related Teacher objects in the same DB query
            classroom = Classroom.objects.select_related("teacher").get(
                classroom_key=classroom_key_from_request
            )

            logger.debug(
                "Classroom key verified: id=%s key=%s",
                classroom.id,
                classroom.classroom_key,
            )

            students_queryset = Student.objects.filter(classroom=classroom)
            students = [
                {"studentName": student.full_name, "studentID": student.pk}
                for student in students_queryset
            ]

            # Get the school directly from the classroom. School is nullable, and
            # CheckClassroomResponseSerializer nests a (non-null) SchoolSerializer,
            # so guard against a school-less classroom instead of 500-ing.
            school = classroom.school
            if school is None:
                logger.warning(
                    "Classroom %s has no school assigned; rejecting key check",
                    classroom.id,
                )
                return Response(
                    {"message": "Classroom is not fully configured (no school assigned)"},
                    status=status.HTTP_409_CONFLICT,
                )

            response_data = {
                "school": school,
                "teacher_data": classroom.teacher.full_name,
                "students": students,
            }
            serializer = CheckClassroomResponseSerializer(
                response_data
            )  # Ensure this serializer is defined
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Classroom.DoesNotExist:
            logger.info(
                "Classroom key verification failed: no classroom for key '%s'",
                classroom_key_from_request,
            )
            return Response(
                {"message": "Classroom key verification failed or classroom not found"},
                status=status.HTTP_404_NOT_FOUND,
            )  # 404 is often more appropriate here
        except Exception:
            # Catch any other unexpected errors
            logger.exception("Unexpected error during classroom key verification")
            return Response(
                {"error": "An internal server error occurred"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class InsertLevelStatisticsView(APIView):
    """
    Inserts run statistics for a student in a given classroom.
    """

    throttle_classes = [AnonRateThrottle]

    def post(self, request, *args, **kwargs):
        input_serializer = LevelStatisticsInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = input_serializer.validated_data
        classroom_key = data["classroomKey"]
        user_full_name = data["user"]
        level_statistics = data["levelStatistics"]

        try:
            classroom = Classroom.objects.get(classroom_key=classroom_key)
        except Classroom.DoesNotExist:
            return Response(
                {"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            student = Student.objects.get(full_name=user_full_name, classroom=classroom)
        except Student.DoesNotExist:
            return Response(
                {"error": "User (Student) not found in this classroom"},
                status=status.HTTP_404_NOT_FOUND,
            )

        player_won = level_statistics.get("place") == 1

        try:
            # Create RunStatistics instance using Django ORM
            run_stat = RunStatistics.objects.create(
                student=student,
                player_won=player_won,
                level=level_statistics.get("level"),
                score=level_statistics.get("score"),
                place=level_statistics.get("place"),
                correct_moves=level_statistics.get("correctMoves"),
                wrong_moves=level_statistics.get("wrongMoves"),
                time_elapsed=level_statistics.get("timeElapsed"),
            )
            # Optionally, serialize and return the created object if needed by the frontend
            # run_stat_serializer = RunStatisticsSerializer(run_stat)
            # return Response(run_stat_serializer.data, status=status.HTTP_201_CREATED)
            return Response(
                {"message": "Data inserted successfully"},
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            # Log the exception for server-side debugging
            print(f"Error inserting run statistics: {e}")
            import traceback

            traceback.print_exc()
            return Response(
                {"error": "Internal server error while saving statistics"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def health_check(request):
    return JsonResponse({"status": "healthy"})


def find_similar_emails(email, model_class, exclude_id=None):
    """
    Find records with similar emails (case-insensitive match but different case).
    Returns a list of records that have the same email in different case.

    Args:
        email: The email to check
        model_class: School or Teacher model class
        exclude_id: ID to exclude from search (the current record)

    Returns:
        List of records with similar emails
    """
    if not email:
        return []

    # Find all records with case-insensitive email match
    from django.db.models import Q

    similar = model_class.objects.filter(Q(status__in=["PENDING", "APPROVED"]))

    # Filter by email field depending on model
    if model_class == School:
        similar = similar.filter(school_email__iexact=email)
    elif model_class == Teacher:
        similar = similar.filter(email__iexact=email)

    # Exclude the current record if provided
    if exclude_id:
        similar = similar.exclude(id=exclude_id)

    # Only return records where the case is actually different
    results = []
    for record in similar:
        record_email = record.school_email if model_class == School else record.email
        if record_email != email:  # Case-sensitive comparison
            results.append(record)

    return results


def send_school_approval_email(school):
    """Send approval notification email to school contact person"""
    logger.info(
        f"Attempting to send approval email to school: {school.name} ({school.contact_person_email})"
    )

    subject = f"School Registration Approved: {school.name}"
    message = f"""Dear {school.contact_person_name or "School Administrator"},

Your school registration has been approved!

School Details:
- Name: {school.name}
- Municipality: {school.municipality}
- Region: {school.region}
- Address: {school.address}

You can now proceed with registering teachers for your school.

Best regards,
DigitMile Team
"""

    # Log email configuration
    logger.info(f"Email backend: {settings.EMAIL_BACKEND}")
    logger.info(f"Email host: {settings.EMAIL_HOST}")
    logger.info(f"From email: {settings.DEFAULT_FROM_EMAIL}")
    logger.info(f"To email: {school.contact_person_email}")

    try:
        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [school.contact_person_email],
            fail_silently=False,
        )
        logger.info(
            f"Email sent successfully to {school.contact_person_email}. Result: {result}"
        )

        # Warn if using console backend (emails won't actually be sent)
        if "console" in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(
            f"Failed to send school approval email to {school.contact_person_email}"
        )
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")


def send_teacher_approval_email(email, username, password, teacher):
    """Send approval notification email with credentials to teacher"""
    logger.info(
        f"Attempting to send approval email to teacher: {teacher.full_name} ({email})"
    )

    subject = "Teacher Registration Approved - Login Credentials"
    message = f"""Dear {teacher.full_name},

Your teacher registration has been approved!

Your login credentials:
- Username: {username}
- Password: {password}

Please login at: {settings.SITE_URL if hasattr(settings, "SITE_URL") else "your login URL"}/admin/

For security reasons, please change your password after your first login.

Schools you're assigned to:
{chr(10).join([f"- {assignment.school.name} ({assignment.years_at_school} years)" for assignment in teacher.school_assignments.all()])}

Best regards,
DigitMile Team
"""

    # Log email configuration
    logger.info(f"Email backend: {settings.EMAIL_BACKEND}")
    logger.info(f"Email host: {settings.EMAIL_HOST}")
    logger.info(f"From email: {settings.DEFAULT_FROM_EMAIL}")
    logger.info(f"To email: {email}")

    try:
        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        logger.info(f"Email sent successfully to {email}. Result: {result}")

        # Warn if using console backend (emails won't actually be sent)
        if "console" in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(f"Failed to send teacher approval email to {email}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")


def send_teacher_registration_email(email, username, password, teacher):
    """Send registration notification email with credentials to teacher (PENDING status)"""
    logger.info(
        f"Attempting to send registration email to teacher: {teacher.full_name} ({email})"
    )

    subject = "Teacher Registration Received - Login Credentials"
    message = f"""Dear {teacher.full_name},

Thank you for registering as a teacher with DigitMile!

Your registration is currently pending approval. However, you can start using the system right away with the following credentials:

Your login credentials:
- Username: {username}
- Password: {password}

Please login at: {settings.SITE_URL if hasattr(settings, "SITE_URL") else "your login URL"}panel/admin/

Schools you're assigned to:
{chr(10).join([f"- {assignment.school.name} ({assignment.years_at_school} years)" for assignment in teacher.school_assignments.all()])}

Note: Your account is pending approval by an administrator. You will be notified once your account has been reviewed.

Best regards,
DigitMile Team
"""

    # Log email configuration
    logger.info(f"Email backend: {settings.EMAIL_BACKEND}")
    logger.info(f"Email host: {settings.EMAIL_HOST}")
    logger.info(f"From email: {settings.DEFAULT_FROM_EMAIL}")
    logger.info(f"To email: {email}")

    try:
        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        logger.info(f"Email sent successfully to {email}. Result: {result}")

        # Warn if using console backend (emails won't actually be sent)
        if "console" in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(f"Failed to send teacher registration email to {email}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")


def send_school_approval_email_for_teacher(teacher):
    """Send approval notification email to teacher (without credentials, since they already have them)"""
    logger.info(
        f"Attempting to send approval notification to teacher: {teacher.full_name} ({teacher.email})"
    )

    subject = "Teacher Registration Approved"
    message = f"""Dear {teacher.full_name},

Great news! Your teacher registration has been approved!

You can continue using your existing login credentials to access the system.

Please login at: {settings.SITE_URL if hasattr(settings, "SITE_URL") else "your login URL"}/admin/

Schools you're assigned to:
{chr(10).join([f"- {assignment.school.name} ({assignment.years_at_school} years)" for assignment in teacher.school_assignments.all()])}

Thank you for being part of DigitMile!

Best regards,
DigitMile Team
"""

    # Log email configuration
    logger.info(f"Email backend: {settings.EMAIL_BACKEND}")
    logger.info(f"Email host: {settings.EMAIL_HOST}")
    logger.info(f"From email: {settings.DEFAULT_FROM_EMAIL}")
    logger.info(f"To email: {teacher.email}")

    try:
        result = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [teacher.email],
            fail_silently=False,
        )
        logger.info(f"Email sent successfully to {teacher.email}. Result: {result}")

        # Warn if using console backend (emails won't actually be sent)
        if "console" in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(f"Failed to send teacher approval notification to {teacher.email}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")


import os


def register_school_view(request):
    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST)
        if form.is_valid():
            # Create school with PENDING status (default)
            school = form.save(commit=False)
            school.status = "PENDING"  # Explicitly set status
            school.save()
            messages.success(request, "School registration submitted for approval.")
            return redirect("registration_success")
    else:
        form = SchoolRegistrationForm()

    context = {"form": form, "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY")}
    return render(request, "digitmileapi/register_school.html", context)


def register_teacher_view(request):
    if request.method == "POST":
        form = TeacherRegistrationForm(request.POST)
        if form.is_valid():
            from django.contrib.auth.models import User, Group
            from django.utils.crypto import get_random_string

            # Create the Teacher instance with PENDING status
            teacher = Teacher.objects.create(
                full_name=form.cleaned_data["full_name"],
                email=form.cleaned_data["email"],
                years_teaching=form.cleaned_data.get("years_teaching"),
                phone_number=form.cleaned_data.get("phone_number", ""),
                status="PENDING",
            )

            # Process selected schools (both pending and approved)
            for school in form.cleaned_data.get("schools", []):
                years_key = f"years_at_school_{school.id}"
                years_at_school = request.POST.get(years_key)
                TeacherSchoolAssignment.objects.create(
                    teacher=teacher,
                    school=school,
                    years_at_school=int(years_at_school)
                    if years_at_school and years_at_school.isdigit()
                    else None,
                )

            # Create user account immediately (even though status is PENDING)
            username = teacher.email.split("@")[0]
            random_password = get_random_string(length=12)

            user = User.objects.create_user(
                username=username,
                email=teacher.email,
                password=random_password,
                is_staff=True,  # Allow access to Django admin
            )

            # Add user to Teachers group
            teachers_group, created = Group.objects.get_or_create(name="Teachers")
            user.groups.add(teachers_group)

            # Link user to teacher
            teacher.user = user
            teacher.save()

            # Send registration email with credentials
            send_teacher_registration_email(
                teacher.email, username, random_password, teacher
            )

            messages.success(
                request,
                "Teacher registration submitted. Login credentials have been sent to your email.",
            )
            return redirect("registration_success")
    else:
        form = TeacherRegistrationForm()
    return render(request, "digitmileapi/register_teacher.html", {"form": form})


class IsTeacher(permissions.BasePermission):
    """
    Custom permission to only allow users in the 'Teachers' group
    who have a PENDING or APPROVED teacher_profile (not REJECTED).
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.groups.filter(name="Teachers").exists()
            and hasattr(request.user, "teacher_profile")
            and request.user.teacher_profile.status in ["PENDING", "APPROVED"]
        )


class TeacherStudentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows teachers to view and manage students
    within their own classrooms.
    """

    serializer_class = TeacherStudentManagementSerializer
    permission_classes = [IsTeacher]  # Use the custom permission

    def get_queryset(self):
        """
        This view should return a list of all the students
        for the currently authenticated teacher's classrooms.
        """
        teacher = self.request.user.teacher_profile
        # Get all classroom IDs for this teacher
        teacher_classroom_ids = Classroom.objects.filter(teacher=teacher).values_list(
            "id", flat=True
        )
        # Filter students who are in any of these classrooms
        return Student.objects.filter(classroom_id__in=teacher_classroom_ids)

    def get_serializer_context(self):
        """
        Pass request to the serializer context.
        """
        return {"request": self.request}

    def perform_create(self, serializer):
        """
        Ensure the student is created within one of the teacher's classrooms.
        The serializer already filters the classroom_id choices.
        This provides an additional check or allows setting it if not provided,
        though the serializer makes classroom_id required for write.
        """
        # The serializer's `classroom_id` field is already filtered to the teacher's classrooms.
        # So, if validation passes, it's implicitly correct.
        # If you wanted to assign to a default classroom of the teacher if not provided,
        # you'd modify the serializer or do it here, but `classroom_id` is currently required.
        serializer.save()

    # perform_update and perform_destroy will also be scoped by get_queryset implicitly
    # ensuring teachers can only modify/delete students they have access to.


class TeacherClassroomListView(generics.ListAPIView):
    """
    API endpoint that allows teachers to view a list of their own classrooms.
    """

    serializer_class = ClassroomBasicSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        """
        This view should return a list of all classrooms
        for the currently authenticated teacher.
        """
        teacher = self.request.user.teacher_profile
        return Classroom.objects.filter(teacher=teacher)


class TeacherSchoolView(generics.ListAPIView):
    """
    API endpoint that allows a teacher to view their assigned schools' details.
    Returns all schools (approved AND pending) assigned to the teacher.
    Teachers can work with pending schools to prepare classrooms/students before approval.
    """

    serializer_class = SchoolSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        """
        Returns all schools (approved and pending) associated with the currently authenticated teacher.
        Teachers should be able to work with pending schools.
        """
        teacher_profile = getattr(self.request.user, "teacher_profile", None)
        if teacher_profile:
            # Return both APPROVED and PENDING schools, exclude REJECTED
            return teacher_profile.schools.exclude(status="REJECTED")
        return School.objects.none()


class TeacherRunStatisticsListView(generics.ListAPIView):
    """
    API endpoint that allows teachers to view run statistics
    for students in their own classrooms.
    """

    serializer_class = RunStatisticsSerializer
    permission_classes = [IsTeacher]

    def get_queryset(self):
        """
        This view should return a list of all run statistics
        for students belonging to the currently authenticated teacher's classrooms.
        """
        teacher = self.request.user.teacher_profile
        # Filter RunStatistics where the student's classroom's teacher is the current teacher
        return RunStatistics.objects.filter(student__classroom__teacher=teacher)


def registration_success(request):
    return render(request, "digitmileapi/registration_success.html")


from django.contrib.auth.decorators import user_passes_test


@user_passes_test(lambda u: u.is_superuser)
def pending_registrations_view(request):
    pending_schools = School.objects.pending()
    pending_teachers = Teacher.objects.pending()

    # Add similar email warnings for schools
    schools_with_warnings = []
    for school in pending_schools:
        similar_emails = find_similar_emails(
            school.school_email, School, exclude_id=school.id
        )
        schools_with_warnings.append(
            {"school": school, "similar_emails": similar_emails}
        )

    # Add similar email warnings for teachers
    teachers_with_warnings = []
    for teacher in pending_teachers:
        similar_emails = find_similar_emails(
            teacher.email, Teacher, exclude_id=teacher.id
        )
        teachers_with_warnings.append(
            {"teacher": teacher, "similar_emails": similar_emails}
        )

    context = {
        "schools_with_warnings": schools_with_warnings,
        "teachers_with_warnings": teachers_with_warnings,
        # Keep original for backwards compatibility if needed
        "pending_schools": pending_schools,
        "pending_teachers": pending_teachers,
    }
    return render(request, "digitmileapi/pending_registrations.html", context)


def home_view(request):
    """
    Home page with integrated login form.
    If user is already authenticated, redirect to admin panel.
    """
    from django.contrib.auth import authenticate, login

    # If user is already logged in, redirect to admin panel
    if request.user.is_authenticated:
        return redirect("/panel/admin/")

    # Handle login form submission
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if username and password:
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                # Redirect to admin panel after successful login
                next_url = request.GET.get("next", "/panel/admin/")
                return redirect(next_url)
            else:
                messages.error(
                    request, "Invalid username or password. Please try again."
                )
        else:
            messages.error(request, "Please enter both username and password.")

    return render(request, "digitmileapi/home.html")


from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User


@user_passes_test(lambda u: u.is_superuser)
def approve_school(request, school_id):
    school = get_object_or_404(School, id=school_id, status="PENDING")

    # Update status to APPROVED
    school.status = "APPROVED"
    school.save()

    # Send approval email to school contact person
    send_school_approval_email(school)

    messages.success(
        request, f"School '{school.name}' has been approved and notified via email."
    )
    return redirect("pending_registrations")


@user_passes_test(lambda u: u.is_superuser)
def reject_school(request, school_id):
    """
    Reject a school registration and cascade rejection to teachers who ONLY have this school.
    Disables login access for rejected teachers while preserving all data.
    """
    school = get_object_or_404(School, id=school_id, status="PENDING")

    # Find all teachers assigned to this school
    teachers_at_school = Teacher.objects.filter(schools=school)

    teachers_to_reject = []
    for teacher in teachers_at_school:
        # Check if this is the teacher's ONLY school
        school_count = teacher.schools.count()
        if school_count == 1:
            # This is their only school, they will be rejected
            teachers_to_reject.append(teacher)

    # Update status to REJECTED (cascade handled in School.save())
    school.status = "REJECTED"
    school.save()

    # Build message
    rejected_teacher_names = [t.full_name for t in teachers_to_reject]
    if rejected_teacher_names:
        teachers_msg = f" The following teachers were also rejected and had login access disabled: {', '.join(rejected_teacher_names)}"
    else:
        teachers_msg = (
            " No teachers were affected (they have assignments to other schools)."
        )

    messages.warning(
        request,
        f"School '{school.name}' has been rejected.{teachers_msg} All data has been preserved for audit purposes.",
    )
    return redirect("pending_registrations")


@user_passes_test(lambda u: u.is_superuser)
def approve_teacher(request, teacher_id):
    from django.contrib.auth.models import Group

    teacher = get_object_or_404(Teacher, id=teacher_id, status="PENDING")

    # Check if user already exists (created during registration)
    if teacher.user:
        # User already exists, just update status to APPROVED
        teacher.status = "APPROVED"
        teacher.save()

        # Send approval notification (without credentials, they already have them)
        send_school_approval_email_for_teacher(teacher)

        messages.success(
            request,
            f"Teacher '{teacher.full_name}' has been approved and notified via email.",
        )
    else:
        # User doesn't exist (old pending teacher), create it now
        username = teacher.email.split("@")[0]
        # Generate a random password
        from django.utils.crypto import get_random_string

        random_password = get_random_string(length=12)

        user = User.objects.create_user(
            username=username,
            email=teacher.email,
            password=random_password,
            is_staff=True,  # Allow access to Django admin
        )

        # Add user to Teachers group
        teachers_group, created = Group.objects.get_or_create(name="Teachers")
        user.groups.add(teachers_group)

        # Link user to teacher and update status
        teacher.user = user
        teacher.status = "APPROVED"
        teacher.save()

        # Send approval email with credentials to teacher
        send_teacher_approval_email(teacher.email, username, random_password, teacher)

        messages.success(
            request,
            f"Teacher '{teacher.full_name}' has been approved and credentials sent via email.",
        )

    return redirect("pending_registrations")


@user_passes_test(lambda u: u.is_superuser)
def reject_teacher(request, teacher_id):
    """
    Reject a teacher registration.
    Disables login access while preserving all classrooms, students, game runs, and analytics for audit purposes.
    """
    teacher = get_object_or_404(Teacher, id=teacher_id, status="PENDING")

    # Count classrooms for informational message
    classrooms_count = Classroom.objects.filter(teacher=teacher).count()

    # Set teacher status to REJECTED (user login disabled in Teacher.save())
    teacher.status = "REJECTED"
    teacher.save()

    messages.warning(
        request,
        f"Teacher '{teacher.full_name}' has been rejected and login access disabled. "
        f"{classrooms_count} classroom(s) and all associated data have been preserved for audit purposes.",
    )
    return redirect("pending_registrations")


from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum, StdDev, Q
from django.utils import timezone
import json
import statistics
from collections import defaultdict
from .analytics import RunAnalytics

# Configuration for enabled visualizations
ENABLED_VISUALIZATIONS = {
    "top_students": True,
    "bottom_students": True,
    "attention_panel": True,
    "rewards_panel": True,
    "learning_curves": True,  # Phase 2 - ENABLED
    "class_comparison": True,  # Phase 2 - ENABLED
    "student_comparison": True,  # Phase 2 - ENABLED
    # Starter Dashboard Visualizations (using new Run/TurnEvent models)
    "win_rate_by_level": True,
    "accuracy_by_level": True,
    "time_by_level": True,
    "speed_vs_accuracy": True,
    "mistake_hotspots": True,
    "special_tile_breakdown": True,
    "decision_time_by_card": True,
    "card_accuracy_by_family": True,
    "card_exposure_by_family": True,
    "decision_time_by_family": True,
    "tile_conditional_accuracy": True,
    "bag_conditional_accuracy": True,
    "conditional_else_rate": True,
    "back_card_usage": True,
    "foreach_tile_context": True,
    "special_chain_lengths": True,
    "number_choice_distribution": True,
    "number_decision_time": True,
}


def _get_filtered_students_for_teacher(
    teacher, grade_filter=None, classroom_filter=None
):
    students = Student.objects.filter(classroom__teacher=teacher)
    if grade_filter:
        students = students.filter(grade=grade_filter)
    if classroom_filter:
        students = students.filter(classroom_id=classroom_filter)
    return students


def _build_teacher_statistics_viz_payload(section, student_ids):
    payload = {}

    if section == "analytics":
        if ENABLED_VISUALIZATIONS.get("win_rate_by_level"):
            payload["win_rate_by_level"] = rollup_win_rate_by_level(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("accuracy_by_level"):
            payload["accuracy_by_level"] = rollup_wrong_moves_rate_by_level(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("time_by_level"):
            payload["time_by_level"] = rollup_time_distribution_by_level(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("speed_vs_accuracy"):
            payload["speed_vs_accuracy"] = RunAnalytics.speed_vs_accuracy_scatter(
                student_ids=student_ids, limit=1000
            )

        if ENABLED_VISUALIZATIONS.get("mistake_hotspots"):
            payload["mistake_hotspots"] = rollup_mistake_hotspots_by_level(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("special_tile_breakdown"):
            payload["special_tile_breakdown"] = rollup_special_tile_breakdown(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("decision_time_by_card"):
            payload["decision_time_by_card"] = rollup_decision_time_by_card_type(
                student_ids=student_ids
            )

    elif section == "turn_insights":
        if ENABLED_VISUALIZATIONS.get("card_exposure_by_family"):
            payload["offer_choice_share_by_family"] = (
                rollup_offer_choice_share_by_family(student_ids=student_ids)
            )
            payload["deck_expected_share_by_family"] = (
                RunAnalytics.deck_expected_share_by_family()
            )

        if ENABLED_VISUALIZATIONS.get("card_accuracy_by_family"):
            payload["card_accuracy_by_family"] = (
                rollup_card_accuracy_by_family_by_level(student_ids=student_ids)
            )

        if ENABLED_VISUALIZATIONS.get("decision_time_by_family"):
            payload["decision_time_by_family"] = (
                rollup_decision_time_by_family_by_level(student_ids=student_ids)
            )

        if ENABLED_VISUALIZATIONS.get("tile_conditional_accuracy"):
            payload["tile_conditional_accuracy"] = (
                rollup_tile_conditional_accuracy_by_tile_type_by_level(
                    student_ids=student_ids
                )
            )

        if ENABLED_VISUALIZATIONS.get("bag_conditional_accuracy"):
            payload["bag_conditional_accuracy"] = (
                rollup_bag_conditional_accuracy_by_comparator_by_level(
                    student_ids=student_ids
                )
            )

        if ENABLED_VISUALIZATIONS.get("back_card_usage"):
            payload["back_card_usage"] = rollup_back_card_usage_by_place_by_level(
                student_ids=student_ids
            )

        if ENABLED_VISUALIZATIONS.get("foreach_tile_context"):
            payload["foreach_tile_context"] = (
                rollup_foreach_tile_context_usage_by_level(student_ids=student_ids)
            )

        if ENABLED_VISUALIZATIONS.get("special_chain_lengths"):
            payload["special_chain_lengths"] = (
                rollup_special_tile_chain_length_distribution_by_level(
                    student_ids=student_ids
                )
            )

        if ENABLED_VISUALIZATIONS.get("number_choice_distribution"):
            payload["number_choice_distribution"] = (
                rollup_number_choice_distribution_by_level(student_ids=student_ids)
            )

        if ENABLED_VISUALIZATIONS.get("number_decision_time"):
            payload["number_decision_time"] = (
                rollup_number_decision_time_by_choice_by_level(student_ids=student_ids)
            )

    return payload


# Helper functions for metric calculations
def calculate_accuracy_rate(correct, wrong):
    """Calculate accuracy as correct / (correct + wrong)"""
    total = correct + wrong
    return (correct / total * 100) if total > 0 else 0


def calculate_decision_time(time_elapsed, correct, wrong):
    """Calculate average decision time per move"""
    total_moves = correct + wrong
    return (time_elapsed / total_moves) if total_moves > 0 else 0


def calculate_weighted_metric(values, timestamps=None, use_recency_weight=True):
    """
    Calculate weighted average with recent values having more weight.
    Uses time-bucket weighting when timestamps are provided.
    """
    if not values:
        return 0

    if not use_recency_weight:
        return sum(values) / len(values)

    if not timestamps or len(timestamps) != len(values):
        weights = [(i + 1) for i in range(len(values))]
        weighted_sum = sum(value * weight for value, weight in zip(values, weights))
        total_weight = sum(weights)
        return weighted_sum / total_weight if total_weight > 0 else 0

    now = timezone.now()
    weights = []
    for timestamp in timestamps:
        if timestamp is None:
            weights.append(1.0)
            continue

        days_ago = (now - timestamp).days
        if days_ago <= 30:
            weight = 3.0
        elif days_ago <= 90:
            weight = 2.0
        elif days_ago <= 180:
            weight = 1.5
        else:
            weight = 1.0
        weights.append(weight)

    weighted_sum = sum(value * weight for value, weight in zip(values, weights))
    total_weight = sum(weights)
    return weighted_sum / total_weight if total_weight > 0 else 0


def calculate_learning_curve_slope(metric_values, min_points=7):
    """
    Calculate the slope of learning curve using simple linear regression.
    Positive = improving, Negative = declining, ~0 = plateaued
    Returns: (slope, trend_label)
    """
    if len(metric_values) < min_points:
        return 0, "insufficient_data"

    n = len(metric_values)
    x = list(range(n))
    y = metric_values

    # Calculate means
    x_mean = sum(x) / n
    y_mean = sum(y) / n

    # Calculate slope using least squares
    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    slope = numerator / denominator if denominator != 0 else 0

    # Classify trend
    avg_performance = y_mean
    if slope > 0.05:
        return slope, "improving"
    elif slope < -0.05:
        return slope, "declining"
    else:
        # Check if plateaued at high performance
        if avg_performance > 80:
            return slope, "mastered"
        return slope, "plateaued"


def calculate_consistency_score(values):
    """
    Calculate consistency as 1 - (std_dev / mean).
    1.0 = perfectly consistent, < 0.7 = highly variable
    """
    if not values or len(values) < 2:
        return 0

    mean_val = statistics.mean(values)
    std_val = statistics.stdev(values)

    if mean_val == 0:
        return 0

    consistency = 1 - (std_val / mean_val)
    return max(0, min(1, consistency))  # Clamp between 0 and 1


_STUDENT_WEEK_HISTORY_FIELDS = (
    "student_id",
    "week_start",
    "runs",
    "wins",
    "correct_moves",
    "wrong_moves",
    "score_sum",
    "score_count",
    "elapsed_sum_ms",
    "elapsed_count",
    "latest_run_id",
    "latest_run__level",
    "latest_run_created_at",
    "first_run_created_at",
)


def _student_weekly_history(student):
    return list(
        StudentWeekStats.objects.filter(student=student)
        .order_by("week_start")
        .values(*_STUDENT_WEEK_HISTORY_FIELDS)
    )


def _bulk_student_weekly_history(student_ids):
    """Bulk-fetch StudentWeekStats for many students in one query.

    Returns {student_id: [weekly_row, ...]} where each row matches the shape
    _student_weekly_history produces for the per-student variant.
    """
    if not student_ids:
        return {}
    rows_by_student = defaultdict(list)
    for row in (
        StudentWeekStats.objects.filter(student_id__in=student_ids)
        .order_by("student_id", "week_start")
        .values(*_STUDENT_WEEK_HISTORY_FIELDS)
    ):
        rows_by_student[row["student_id"]].append(row)
    return rows_by_student


def _student_weekly_level_history(student):
    return list(
        StudentWeekLevelStats.objects.filter(student=student)
        .order_by("week_start", "level")
        .values(
            "week_start",
            "level",
            "runs",
            "wins",
            "correct_moves",
            "wrong_moves",
            "score_sum",
            "score_count",
            "elapsed_sum_ms",
            "elapsed_count",
            "latest_run_created_at",
        )
    )


def _build_student_dashboard_info(student, weekly_rows=None, bucket_data=None):
    """Build the per-student dashboard info dict.

    When the caller has already bulk-fetched weekly history and bucket
    points (the dashboard view path), pass them in to skip the per-student
    queries. Callers without pre-fetched data (benchmarks, tests) get the
    original behaviour.
    """
    if weekly_rows is None:
        weekly_rows = _student_weekly_history(student)
    if not weekly_rows:
        return None

    if bucket_data is None:
        bucket_data = get_student_run_bucket_points(student)
    bucket_points = bucket_data["points"]
    total_runs = sum(row["runs"] or 0 for row in weekly_rows)
    wins = sum(row["wins"] or 0 for row in weekly_rows)

    total_correct = sum(row["correct_moves"] or 0 for row in weekly_rows)
    total_wrong = sum(row["wrong_moves"] or 0 for row in weekly_rows)
    total_elapsed_ms = sum(row["elapsed_sum_ms"] or 0 for row in weekly_rows)

    score_values = []
    score_timestamps = []
    time_values = []
    accuracy_values = []
    correct_moves_list = []
    wrong_moves_list = []
    scores = []
    times = []
    levels = []
    accuracy_per_game = []
    latest_run_id = None
    latest_run_level = None
    latest_run_created_at = None

    for row in weekly_rows:
        if row["latest_run_created_at"] and (
            latest_run_created_at is None
            or row["latest_run_created_at"] > latest_run_created_at
        ):
            latest_run_id = row["latest_run_id"]
            latest_run_level = row["latest_run__level"]
            latest_run_created_at = row["latest_run_created_at"]

    for point in bucket_points:
        if point["score"] is not None:
            score_values.append(point["score"])
            score_timestamps.append(point["last_run_created_at"])
        if point["time_seconds"] is not None:
            time_values.append(point["time_seconds"])

        scores.append(point["score"])
        times.append(point["time_seconds"])
        accuracy_values.append(point["accuracy"])
        accuracy_per_game.append(point["accuracy"])
        correct_moves_list.append(point["correct_moves"])
        wrong_moves_list.append(point["wrong_moves"])
        levels.append(point["level"])

    overall_accuracy = calculate_accuracy_rate(total_correct, total_wrong)
    avg_decision_time = calculate_decision_time(
        total_elapsed_ms / 1000,
        total_correct,
        total_wrong,
    )
    weighted_avg_score = calculate_weighted_metric(
        score_values,
        timestamps=score_timestamps,
        use_recency_weight=True,
    )

    improvement_rate = 0
    if len(accuracy_values) >= 3:
        sample_size = min(3, max(2, len(accuracy_values) // 2))
        initial_avg = sum(accuracy_values[:sample_size]) / sample_size
        recent_avg = sum(accuracy_values[-sample_size:]) / sample_size
        if initial_avg > 0:
            improvement_rate = ((recent_avg - initial_avg) / initial_avg) * 100

    consistency = calculate_consistency_score(score_values) if score_values else 0
    learning_curve_slope = 0
    learning_curve_trend = "insufficient_data"
    if len(accuracy_values) >= 3:
        learning_curve_slope, learning_curve_trend = calculate_learning_curve_slope(
            accuracy_values,
            min_points=3,
        )

    level_performance = defaultdict(
        lambda: {
            "attempts": [],
            "accuracy_values": [],
            "score_values": [],
            "time_values": [],
            "learning_curve_slope": 0,
            "learning_curve_trend": "insufficient_data",
        }
    )

    for level, points in bucket_data["by_level"].items():
        for point in points:
            level_performance[level]["attempts"].append(
                len(level_performance[level]["attempts"]) + 1
            )
            level_performance[level]["accuracy_values"].append(point["accuracy"])
            level_performance[level]["score_values"].append(point["score"])
            level_performance[level]["time_values"].append(point["time_seconds"])

    for level, data in level_performance.items():
        accuracy_values_for_trend = [
            value for value in data["accuracy_values"] if value is not None
        ]
        if len(accuracy_values_for_trend) >= 3:
            slope, trend = calculate_learning_curve_slope(
                accuracy_values_for_trend,
                min_points=3,
            )
            data["learning_curve_slope"] = slope
            data["learning_curve_trend"] = trend

    wrong_move_ratio = (
        (total_wrong / (total_correct + total_wrong))
        if (total_correct + total_wrong) > 0
        else 0
    )
    needs_attention = False
    attention_reason = []
    if learning_curve_trend == "declining":
        needs_attention = True
        attention_reason.append("Declining performance")
    if wrong_move_ratio > 0.5:
        needs_attention = True
        attention_reason.append(
            f"High error rate ({wrong_move_ratio * 100:.1f}% wrong moves)"
        )

    ready_for_reward = False
    reward_reason = []
    if learning_curve_trend == "improving" and learning_curve_slope > 0.1:
        ready_for_reward = True
        reward_reason.append("Strong improvement")
    if overall_accuracy >= 90:
        ready_for_reward = True
        reward_reason.append("Exceptional accuracy")
    if consistency > 0.85 and weighted_avg_score > 0:
        ready_for_reward = True
        reward_reason.append("Consistent excellence")

    return {
        "id": student.id,
        "name": student.full_name,
        "classroom": student.classroom.classroom_name,
        "classroom_id": student.classroom.id,
        "classroom_key": student.classroom.classroom_key,
        "grade": student.grade,
        "total_runs": total_runs,
        "wins": wins,
        "win_rate": (wins / total_runs * 100) if total_runs > 0 else 0,
        "latest_run_id": latest_run_id,
        "latest_run_level": latest_run_level,
        "latest_run_created_at": latest_run_created_at,
        "accuracy": overall_accuracy,
        "avg_score": weighted_avg_score,
        "avg_decision_time": avg_decision_time,
        "improvement_rate": improvement_rate,
        "consistency": consistency,
        "learning_curve_slope": learning_curve_slope,
        "learning_curve_trend": learning_curve_trend,
        "level_performance": dict(level_performance),
        "levels": levels,
        "scores": scores,
        "times": times,
        "correct_moves": correct_moves_list,
        "wrong_moves": wrong_moves_list,
        "places": [None for _ in levels],
        "accuracy_per_game": accuracy_per_game,
        "needs_attention": needs_attention,
        "attention_reason": ", ".join(attention_reason),
        "ready_for_reward": ready_for_reward,
        "reward_reason": ", ".join(reward_reason),
    }


_CLASSROOM_WEEK_STATS_FIELDS = (
    "classroom_id",
    "student_count",
    "runs",
    "wins",
    "correct_moves",
    "wrong_moves",
    "score_sum",
    "score_count",
    "elapsed_sum_ms",
)


def _bulk_classroom_weekly_history(classroom_ids):
    """Bulk-fetch ClassroomWeekStats keyed by classroom_id."""
    if not classroom_ids:
        return {}
    rows_by_classroom = defaultdict(list)
    for row in ClassroomWeekStats.objects.filter(
        classroom_id__in=classroom_ids
    ).values(*_CLASSROOM_WEEK_STATS_FIELDS):
        rows_by_classroom[row["classroom_id"]].append(row)
    return rows_by_classroom


def _build_classroom_dashboard_stats(
    classroom, grade_filter=None, weekly_rows=None, student_count=None
):
    if grade_filter and str(classroom.grade) != str(grade_filter):
        return None

    if weekly_rows is None:
        weekly_rows = list(
            ClassroomWeekStats.objects.filter(classroom=classroom).values(
                *_CLASSROOM_WEEK_STATS_FIELDS
            )
        )

    if not weekly_rows:
        return None

    total_correct = sum(row["correct_moves"] or 0 for row in weekly_rows)
    total_wrong = sum(row["wrong_moves"] or 0 for row in weekly_rows)
    total_elapsed_ms = sum(row["elapsed_sum_ms"] or 0 for row in weekly_rows)
    total_runs = sum(row["runs"] or 0 for row in weekly_rows)
    wins = sum(row["wins"] or 0 for row in weekly_rows)
    score_sum = sum(row["score_sum"] or 0 for row in weekly_rows)
    score_count = sum(row["score_count"] or 0 for row in weekly_rows)

    if student_count is None:
        student_count = (
            classroom.students.filter(grade=grade_filter).count()
            if grade_filter
            else classroom.students.count()
        )
    classroom_accuracy = calculate_accuracy_rate(total_correct, total_wrong)
    avg_decision_time = calculate_decision_time(
        total_elapsed_ms / 1000,
        total_correct,
        total_wrong,
    )
    engagement = (total_runs / student_count) if student_count > 0 else 0

    return {
        "id": classroom.id,
        "name": classroom.classroom_name,
        "key": classroom.classroom_key,
        "grade": classroom.grade,
        "student_count": student_count,
        "total_runs": total_runs,
        "avg_score": (score_sum / score_count) if score_count > 0 else 0,
        "win_rate": (wins / total_runs * 100) if total_runs > 0 else 0,
        "accuracy": classroom_accuracy,
        "avg_decision_time": avg_decision_time,
        "engagement": engagement,
    }


@login_required
@user_passes_test(
    lambda u: hasattr(u, "teacher_profile")
    and u.teacher_profile.status in ["PENDING", "APPROVED"]
)
def teacher_statistics_viz_data(request):
    teacher = request.user.teacher_profile
    section = request.GET.get("section")

    if section not in {"analytics", "turn_insights"}:
        return JsonResponse(
            {"error": "Invalid section. Expected 'analytics' or 'turn_insights'."},
            status=400,
        )

    grade_filter = request.GET.get("grade", None)
    classroom_filter = request.GET.get("classroom", None)
    cache_key = (
        f"teacher_stats_viz:{teacher.id}:{section}:"
        f"{grade_filter or 'all'}:{classroom_filter or 'all'}"
    )
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return JsonResponse({"section": section, "data": cached_payload})

    students = _get_filtered_students_for_teacher(
        teacher=teacher,
        grade_filter=grade_filter,
        classroom_filter=classroom_filter,
    )
    filtered_student_ids = list(students.values_list("id", flat=True))
    payload = _build_teacher_statistics_viz_payload(section, filtered_student_ids)
    cache.set(cache_key, payload, timeout=604800)
    return JsonResponse({"section": section, "data": payload})


def _compute_teacher_dashboard_data(teacher, grade_filter, classroom_filter):
    """Return the per-teacher dashboard data payload (no ORM objects).

    All structured lists in the result are JSON-serialisable, so the value
    is safe to put in cache. The view layer wraps this and adds the
    request-time bits (Teacher object, grades, classroom list).
    """
    all_classrooms = list(Classroom.objects.filter(teacher=teacher))
    if classroom_filter:
        classrooms = [c for c in all_classrooms if str(c.id) == str(classroom_filter)]
    else:
        classrooms = all_classrooms

    students = list(
        _get_filtered_students_for_teacher(
            teacher=teacher,
            grade_filter=grade_filter,
            classroom_filter=classroom_filter,
        ).select_related("classroom")
    )
    if classroom_filter:
        comparison_students_qs = Student.objects.filter(classroom__teacher=teacher)
        if grade_filter:
            comparison_students_qs = comparison_students_qs.filter(grade=grade_filter)
        comparison_students = list(
            comparison_students_qs.select_related("classroom")
        )
    else:
        comparison_students = students

    # Bulk-fetch once for the union of students we'll need to render.
    all_student_ids = list({s.id for s in students} | {s.id for s in comparison_students})
    weekly_by_student = _bulk_student_weekly_history(all_student_ids)
    buckets_by_student = bulk_student_run_bucket_points(all_student_ids)

    def build_info(student):
        return _build_student_dashboard_info(
            student,
            weekly_rows=weekly_by_student.get(student.id, []),
            bucket_data=buckets_by_student.get(
                student.id, {"points": [], "by_level": {}}
            ),
        )

    student_data = []
    students_needing_attention = []
    students_ready_for_rewards = []
    for student in students:
        info = build_info(student)
        if not info:
            continue
        student_data.append(info)
        if info["needs_attention"]:
            students_needing_attention.append(info)
        if info["ready_for_reward"]:
            students_ready_for_rewards.append(info)

    if classroom_filter:
        comparison_student_data = []
        for student in comparison_students:
            info = build_info(student)
            if info:
                comparison_student_data.append(info)
    else:
        comparison_student_data = list(student_data)

    top_by_accuracy = sorted(
        student_data, key=lambda x: x["accuracy"], reverse=True
    )[:10]
    top_by_improvement = sorted(
        [s for s in student_data if s["improvement_rate"] != 0],
        key=lambda x: x["improvement_rate"],
        reverse=True,
    )[:10]
    bottom_by_accuracy = sorted(student_data, key=lambda x: x["accuracy"])[:10]
    bottom_by_learning_curve = sorted(
        [
            s
            for s in student_data
            if s["learning_curve_trend"] in ["declining", "plateaued"]
            and s["accuracy"] < 80
        ],
        key=lambda x: x["learning_curve_slope"],
    )[:10]

    # Bulk-fetch ClassroomWeekStats and per-classroom student counts for the
    # classroom panels.
    classroom_ids_for_stats = list({c.id for c in classrooms} | {c.id for c in all_classrooms})
    classroom_weekly_by_id = _bulk_classroom_weekly_history(classroom_ids_for_stats)
    student_count_by_classroom = defaultdict(int)
    student_count_query = Student.objects.filter(
        classroom_id__in=classroom_ids_for_stats
    )
    if grade_filter:
        student_count_query = student_count_query.filter(grade=grade_filter)
    for entry in (
        student_count_query.values("classroom_id")
        .annotate(student_count=Count("id"))
    ):
        student_count_by_classroom[entry["classroom_id"]] = entry["student_count"]

    def build_classroom_stats(classrooms_iter):
        stats = []
        for classroom in classrooms_iter:
            info = _build_classroom_dashboard_stats(
                classroom,
                grade_filter=grade_filter,
                weekly_rows=classroom_weekly_by_id.get(classroom.id, []),
                student_count=student_count_by_classroom.get(classroom.id, 0),
            )
            if info:
                stats.append(info)
        return stats

    classroom_stats = build_classroom_stats(classrooms)
    if classroom_filter:
        comparison_classroom_stats = build_classroom_stats(all_classrooms)
    else:
        comparison_classroom_stats = list(classroom_stats)

    return {
        "student_data": student_data,
        "comparison_student_data": comparison_student_data,
        "classroom_stats": classroom_stats,
        "comparison_classroom_stats": comparison_classroom_stats,
        "top_by_accuracy": top_by_accuracy,
        "top_by_improvement": top_by_improvement,
        "bottom_by_accuracy": bottom_by_accuracy,
        "bottom_by_learning_curve": bottom_by_learning_curve,
        "students_needing_attention": students_needing_attention,
        "students_ready_for_rewards": students_ready_for_rewards,
    }


def _teacher_dashboard_cache_key(teacher_id, grade_filter, classroom_filter):
    return (
        f"teacher_dashboard:{teacher_id}:"
        f"{grade_filter or 'all'}:{classroom_filter or 'all'}"
    )


@login_required
@user_passes_test(
    lambda u: hasattr(u, "teacher_profile")
    and u.teacher_profile.status in ["PENDING", "APPROVED"]
)
def teacher_statistics_dashboard(request):
    """
    Enhanced dashboard for teachers to view comprehensive student performance statistics.
    Includes learning curves, top/bottom performers, attention/reward panels.
    Accessible to PENDING and APPROVED teachers.
    """
    teacher = request.user.teacher_profile
    grade_filter = request.GET.get("grade", None)
    classroom_filter = request.GET.get("classroom", None)

    cache_key = _teacher_dashboard_cache_key(teacher.id, grade_filter, classroom_filter)
    payload = cache.get(cache_key)
    if payload is None:
        payload = _compute_teacher_dashboard_data(
            teacher, grade_filter, classroom_filter
        )
        cache.set(cache_key, payload, timeout=604800)

    all_grades = (
        Student.objects.filter(classroom__teacher=teacher)
        .values_list("grade", flat=True)
        .distinct()
        .order_by("grade")
    )
    classroom_list = Classroom.objects.filter(teacher=teacher).order_by(
        "classroom_name"
    )

    starter_viz_data = {}

    context = {
        "teacher": teacher,
        "student_data": payload["student_data"],
        "student_data_json": json.dumps(payload["student_data"], default=str),
        "comparison_student_data": payload["comparison_student_data"],
        "comparison_student_data_json": json.dumps(
            payload["comparison_student_data"], default=str
        ),
        "classroom_stats": payload["classroom_stats"],
        "classroom_stats_json": json.dumps(payload["classroom_stats"], default=str),
        "comparison_classroom_stats": payload["comparison_classroom_stats"],
        "comparison_classroom_stats_json": json.dumps(
            payload["comparison_classroom_stats"], default=str
        ),
        # Enhanced panels
        "top_by_accuracy": payload["top_by_accuracy"],
        "top_by_improvement": payload["top_by_improvement"],
        "bottom_by_accuracy": payload["bottom_by_accuracy"],
        "bottom_by_learning_curve": payload["bottom_by_learning_curve"],
        "students_needing_attention": payload["students_needing_attention"],
        "students_ready_for_rewards": payload["students_ready_for_rewards"],
        # Filters
        "all_grades": all_grades,
        "classroom_list": classroom_list,
        "selected_grade": grade_filter,
        "selected_classroom": classroom_filter,
        # Enabled visualizations
        "enabled_viz": ENABLED_VISUALIZATIONS,
        # Starter Dashboard Visualization Data
        "starter_viz_data_json": json.dumps(starter_viz_data, default=str),
    }

    return render(request, "digitmileapi/teacher_statistics.html", context)


@login_required
def teacher_run_replay(request, run_id):
    teacher = getattr(request.user, "teacher_profile", None)
    if request.user.is_superuser:
        run = get_object_or_404(Run, id=run_id)
    else:
        run = get_object_or_404(
            Run,
            id=run_id,
            student__classroom__teacher=teacher,
        )

    run_data = get_replay_payload_for_run(run)

    context = {
        "teacher": teacher,
        "run": run,
        "run_data_json": json.dumps(run_data, default=str),
    }

    return render(request, "digitmileapi/teacher_run_replay.html", context)
