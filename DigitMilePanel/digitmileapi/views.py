# myapi/views.py
from rest_framework import generics # For ListAPIView
from .serializers import ClassroomBasicSerializer # To serialize classroom data
from .serializers import SchoolSerializer # Ensure SchoolSerializer is imported
from .serializers import RunStatisticsSerializer # Ensure RunStatisticsSerializer is imported
from rest_framework import viewsets, permissions
from .serializers import TeacherStudentManagementSerializer # Add this new serializer
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse_lazy
from .forms import SchoolRegistrationForm, TeacherRegistrationForm
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Classroom, Student, Teacher, School, RunStatistics, TeacherSchoolAssignment
from .serializers import (
    CheckClassroomResponseSerializer,
    LevelStatisticsInputSerializer,
    RunStatisticsSerializer # Import if you use it for creation validation/response
)
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse
import logging

# Set up logger for email operations
logger = logging.getLogger(__name__)

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
    similar = model_class.objects.filter(
        Q(status__in=['PENDING', 'APPROVED'])
    )

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
    logger.info(f"Attempting to send approval email to school: {school.name} ({school.contact_person_email})")

    subject = f'School Registration Approved: {school.name}'
    message = f'''Dear {school.contact_person_name or 'School Administrator'},

Your school registration has been approved!

School Details:
- Name: {school.name}
- Municipality: {school.municipality}
- Region: {school.region}
- Address: {school.address}

You can now proceed with registering teachers for your school.

Best regards,
DigitMile Team
'''

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
        logger.info(f"Email sent successfully to {school.contact_person_email}. Result: {result}")

        # Warn if using console backend (emails won't actually be sent)
        if 'console' in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(f"Failed to send school approval email to {school.contact_person_email}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")

def send_teacher_approval_email(email, username, password, teacher):
    """Send approval notification email with credentials to teacher"""
    logger.info(f"Attempting to send approval email to teacher: {teacher.full_name} ({email})")

    subject = 'Teacher Registration Approved - Login Credentials'
    message = f'''Dear {teacher.full_name},

Your teacher registration has been approved!

Your login credentials:
- Username: {username}
- Password: {password}

Please login at: {settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'your login URL'}/admin/

For security reasons, please change your password after your first login.

Schools you're assigned to:
{chr(10).join([f"- {assignment.school.name} ({assignment.years_at_school} years)" for assignment in teacher.school_assignments.all()])}

Best regards,
DigitMile Team
'''

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
        if 'console' in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"⚠️  Using console backend - email was printed to console but NOT sent to inbox. "
                f"To send real emails, configure SMTP settings in .env"
            )
    except Exception as e:
        logger.error(f"Failed to send teacher approval email to {email}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.exception("Full traceback:")

class CheckClassroomKeyView(APIView):
    """
    Checks if a classroom key exists and returns classroom, teacher, and student data.
    """
    def post(self, request, *args, **kwargs):
        classroom_key_from_request = request.data.get("classroomKey")

        if not classroom_key_from_request:
            return Response({"error": "Invalid input: classroomKey missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Fetch the classroom using its unique classroom_key
            # select_related fetches related Teacher objects in the same DB query
            print(Classroom.objects.count())

            classroom = Classroom.objects.select_related('teacher').get(classroom_key=classroom_key_from_request)

            # Now you can safely access classroom attributes
            print(f"Found classroom: ID={classroom.id}, Key={classroom.classroom_key}, Teacher={classroom.teacher.full_name}")

            # ... (rest of your logic to prepare response_data)
            students_queryset = Student.objects.filter(classroom=classroom)
            student_names = [student.full_name for student in students_queryset]

            # Get the school directly from the classroom
            school = classroom.school

            response_data = {
                'school': school,
                'teacher_data': classroom.teacher.full_name,
                'students': student_names
            }
            serializer = CheckClassroomResponseSerializer(response_data) # Ensure this serializer is defined
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Classroom.DoesNotExist:
            print(f"Classroom with key '{classroom_key_from_request}' does not exist.") # More informative print
            return Response({"message": "Classroom key verification failed or classroom not found"}, status=status.HTTP_404_NOT_FOUND) # 404 is often more appropriate here
        except Exception as e:
            # Catch any other unexpected errors
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": "An internal server error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class InsertLevelStatisticsView(APIView):
    """
    Inserts run statistics for a student in a given classroom.
    """
    def post(self, request, *args, **kwargs):
        input_serializer = LevelStatisticsInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = input_serializer.validated_data
        classroom_key = data["classroomKey"]
        user_full_name = data["user"]
        level_statistics = data['levelStatistics']

        try:
            classroom = Classroom.objects.get(classroom_key=classroom_key)
        except Classroom.DoesNotExist:
            return Response({"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            student = Student.objects.get(full_name=user_full_name, classroom=classroom)
        except Student.DoesNotExist:
            return Response({"error": "User (Student) not found in this classroom"}, status=status.HTTP_404_NOT_FOUND)

        player_won = level_statistics.get('place') == 1

        try:
            # Create RunStatistics instance using Django ORM
            run_stat = RunStatistics.objects.create(
                student=student,
                player_won=player_won,
                level=level_statistics.get('level'),
                score=level_statistics.get('score'),
                place=level_statistics.get('place'),
                correct_moves=level_statistics.get('correctMoves'),
                wrong_moves=level_statistics.get('wrongMoves'),
                time_elapsed=level_statistics.get('timeElapsed')
            )
            # Optionally, serialize and return the created object if needed by the frontend
            # run_stat_serializer = RunStatisticsSerializer(run_stat)
            # return Response(run_stat_serializer.data, status=status.HTTP_201_CREATED)
            return Response({"message": "Data inserted successfully"}, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Log the exception for server-side debugging
            print(f"Error inserting run statistics: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": "Internal server error while saving statistics"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
import os

def register_school_view(request):
    if request.method == 'POST':
        form = SchoolRegistrationForm(request.POST)
        if form.is_valid():
            # Create school with PENDING status (default)
            school = form.save(commit=False)
            school.status = 'PENDING'  # Explicitly set status
            school.save()
            messages.success(request, 'School registration submitted for approval.')
            return redirect('registration_success')
    else:
        form = SchoolRegistrationForm()

    context = {
        'form': form,
        'google_maps_api_key': os.getenv('GOOGLE_MAPS_API_KEY')
    }
    return render(request, 'digitmileapi/register_school.html', context)

def register_teacher_view(request):
    if request.method == 'POST':
        form = TeacherRegistrationForm(request.POST)
        if form.is_valid():
            # Create the Teacher instance with PENDING status
            teacher = Teacher.objects.create(
                full_name=form.cleaned_data['full_name'],
                email=form.cleaned_data['email'],
                years_teaching=form.cleaned_data.get('years_teaching'),
                phone_number=form.cleaned_data.get('phone_number', ''),
                status='PENDING'
            )

            # Process selected schools (both pending and approved)
            for school in form.cleaned_data.get('schools', []):
                years_key = f'years_at_school_{school.id}'
                years_at_school = request.POST.get(years_key)
                TeacherSchoolAssignment.objects.create(
                    teacher=teacher,
                    school=school,
                    years_at_school=int(years_at_school) if years_at_school and years_at_school.isdigit() else None
                )

            messages.success(request, 'Teacher registration submitted for approval.')
            return redirect('registration_success')
    else:
        form = TeacherRegistrationForm()
    return render(request, 'digitmileapi/register_teacher.html', {'form': form})
class IsTeacher(permissions.BasePermission):
    """
    Custom permission to only allow users in the 'Teachers' group
    and who have a teacher_profile.
    """
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.groups.filter(name='Teachers').exists() and
            hasattr(request.user, 'teacher_profile')
        )

class TeacherStudentViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows teachers to view and manage students
    within their own classrooms.
    """
    serializer_class = TeacherStudentManagementSerializer
    permission_classes = [IsTeacher] # Use the custom permission

    def get_queryset(self):
        """
        This view should return a list of all the students
        for the currently authenticated teacher's classrooms.
        """
        teacher = self.request.user.teacher_profile
        # Get all classroom IDs for this teacher
        teacher_classroom_ids = Classroom.objects.filter(teacher=teacher).values_list('id', flat=True)
        # Filter students who are in any of these classrooms
        return Student.objects.filter(classroom_id__in=teacher_classroom_ids)

    def get_serializer_context(self):
        """
        Pass request to the serializer context.
        """
        return {'request': self.request}

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
        teacher_profile = getattr(self.request.user, 'teacher_profile', None)
        if teacher_profile:
            # Return both APPROVED and PENDING schools, exclude REJECTED
            return teacher_profile.schools.exclude(status='REJECTED')
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
    return render(request, 'digitmileapi/registration_success.html')
from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_superuser)
def pending_registrations_view(request):
    pending_schools = School.objects.pending()
    pending_teachers = Teacher.objects.pending()

    # Add similar email warnings for schools
    schools_with_warnings = []
    for school in pending_schools:
        similar_emails = find_similar_emails(school.school_email, School, exclude_id=school.id)
        schools_with_warnings.append({
            'school': school,
            'similar_emails': similar_emails
        })

    # Add similar email warnings for teachers
    teachers_with_warnings = []
    for teacher in pending_teachers:
        similar_emails = find_similar_emails(teacher.email, Teacher, exclude_id=teacher.id)
        teachers_with_warnings.append({
            'teacher': teacher,
            'similar_emails': similar_emails
        })

    context = {
        'schools_with_warnings': schools_with_warnings,
        'teachers_with_warnings': teachers_with_warnings,
        # Keep original for backwards compatibility if needed
        'pending_schools': pending_schools,
        'pending_teachers': pending_teachers,
    }
    return render(request, 'digitmileapi/pending_registrations.html', context)
def home_view(request):
    return render(request, 'digitmileapi/home.html')
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User

@user_passes_test(lambda u: u.is_superuser)
def approve_school(request, school_id):
    school = get_object_or_404(School, id=school_id, status='PENDING')

    # Update status to APPROVED
    school.status = 'APPROVED'
    school.save()

    # Send approval email to school contact person
    send_school_approval_email(school)

    messages.success(request, f"School '{school.name}' has been approved and notified via email.")
    return redirect('pending_registrations')

@user_passes_test(lambda u: u.is_superuser)
def reject_school(request, school_id):
    """
    Reject a school registration and cascade rejection to teachers who ONLY have this school.
    Deletes all classrooms, students, and run statistics for rejected teachers.
    """
    school = get_object_or_404(School, id=school_id, status='PENDING')

    # Find all teachers assigned to this school
    teachers_at_school = Teacher.objects.filter(schools=school)

    teachers_to_reject = []
    for teacher in teachers_at_school:
        # Check if this is the teacher's ONLY school
        school_count = teacher.schools.count()
        if school_count == 1:
            # This is their only school, they will be rejected
            teachers_to_reject.append(teacher)

    # Update status to REJECTED
    school.status = 'REJECTED'
    school.save()

    # Reject teachers who only have this school
    rejected_teacher_names = []
    for teacher in teachers_to_reject:
        # Delete all classrooms (cascades to students and run statistics)
        Classroom.objects.filter(teacher=teacher).delete()

        # Set teacher status to REJECTED
        teacher.status = 'REJECTED'
        teacher.save()

        rejected_teacher_names.append(teacher.full_name)

    # Build message
    if rejected_teacher_names:
        teachers_msg = f" The following teachers were also rejected and their data deleted: {', '.join(rejected_teacher_names)}"
    else:
        teachers_msg = " No teachers were affected (they have assignments to other schools)."

    messages.warning(
        request,
        f"School '{school.name}' has been rejected.{teachers_msg}"
    )
    return redirect('pending_registrations')

@user_passes_test(lambda u: u.is_superuser)
def approve_teacher(request, teacher_id):
    from django.contrib.auth.models import Group

    teacher = get_object_or_404(Teacher, id=teacher_id, status='PENDING')

    # Create a new user for the teacher
    username = teacher.email.split('@')[0]
    # Generate a random password
    from django.utils.crypto import get_random_string
    random_password = get_random_string(length=12)

    user = User.objects.create_user(
        username=username,
        email=teacher.email,
        password=random_password,
        is_staff=True  # Allow access to Django admin
    )

    # Add user to Teachers group
    teachers_group, created = Group.objects.get_or_create(name='Teachers')
    user.groups.add(teachers_group)

    # Link user to teacher and update status
    teacher.user = user
    teacher.status = 'APPROVED'
    teacher.save()

    # Send approval email with credentials to teacher
    send_teacher_approval_email(teacher.email, username, random_password, teacher)

    messages.success(request, f"Teacher '{teacher.full_name}' has been approved and credentials sent via email.")
    return redirect('pending_registrations')

@user_passes_test(lambda u: u.is_superuser)
def reject_teacher(request, teacher_id):
    """
    Reject a teacher registration.
    Deletes all classrooms, students, and run statistics created by this teacher.
    """
    teacher = get_object_or_404(Teacher, id=teacher_id, status='PENDING')

    # Delete all classrooms (cascades to students and run statistics)
    classrooms_deleted = Classroom.objects.filter(teacher=teacher).count()
    Classroom.objects.filter(teacher=teacher).delete()

    # Set teacher status to REJECTED
    teacher.status = 'REJECTED'
    teacher.save()

    messages.warning(
        request,
        f"Teacher '{teacher.full_name}' has been rejected. {classrooms_deleted} classroom(s) and all associated data were deleted."
    )
    return redirect('pending_registrations')

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum, StdDev
import json
import statistics
from collections import defaultdict

# Configuration for enabled visualizations
ENABLED_VISUALIZATIONS = {
    'top_students': True,
    'bottom_students': True,
    'attention_panel': True,
    'rewards_panel': True,
    'learning_curves': True,  # Phase 2 - ENABLED
    'class_comparison': True,  # Phase 2 - ENABLED
    'student_comparison': True,  # Phase 2 - ENABLED
}

# Helper functions for metric calculations
def calculate_accuracy_rate(correct, wrong):
    """Calculate accuracy as correct / (correct + wrong)"""
    total = correct + wrong
    return (correct / total * 100) if total > 0 else 0

def calculate_decision_time(time_elapsed, correct, wrong):
    """Calculate average decision time per move"""
    total_moves = correct + wrong
    return (time_elapsed / total_moves) if total_moves > 0 else 0

def calculate_weighted_metric(values, use_recency_weight=True):
    """
    Calculate weighted average with recent values having more weight.
    Assumes values are in chronological order.
    """
    if not values:
        return 0

    if not use_recency_weight:
        return sum(values) / len(values)

    # Simple linear weighting: more recent = higher weight
    weights = [(i + 1) for i in range(len(values))]
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    total_weight = sum(weights)
    return weighted_sum / total_weight if total_weight > 0 else 0

def calculate_learning_curve_slope(metric_values):
    """
    Calculate the slope of learning curve using simple linear regression.
    Positive = improving, Negative = declining, ~0 = plateaued
    Returns: (slope, trend_label)
    """
    if len(metric_values) < 7:
        return 0, 'insufficient_data'

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
        return slope, 'improving'
    elif slope < -0.05:
        return slope, 'declining'
    else:
        # Check if plateaued at high performance
        if avg_performance > 80:
            return slope, 'mastered'
        return slope, 'plateaued'

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

@login_required
@user_passes_test(lambda u: hasattr(u, 'teacher_profile'))
def teacher_statistics_dashboard(request):
    """
    Enhanced dashboard for teachers to view comprehensive student performance statistics.
    Includes learning curves, top/bottom performers, attention/reward panels.
    """
    teacher = request.user.teacher_profile

    # Get filters from request
    grade_filter = request.GET.get('grade', None)
    classroom_filter = request.GET.get('classroom', None)

    # Get all classrooms for this teacher
    classrooms = Classroom.objects.filter(teacher=teacher).prefetch_related('students')

    # Apply classroom filter if specified
    if classroom_filter:
        classrooms = classrooms.filter(id=classroom_filter)

    # Get all students for this teacher
    students = Student.objects.filter(classroom__teacher=teacher)

    # Apply grade filter if specified
    if grade_filter:
        students = students.filter(grade=grade_filter)

    # Apply classroom filter if specified
    if classroom_filter:
        students = students.filter(classroom_id=classroom_filter)

    # Prepare enhanced data for each student
    student_data = []
    students_needing_attention = []
    students_ready_for_rewards = []

    for student in students:
        stats = RunStatistics.objects.filter(student=student).order_by('id')  # Chronological order

        if not stats.exists():
            continue

        # Basic metrics
        total_runs = stats.count()
        wins = stats.filter(player_won=True).count()
        win_rate = (wins / total_runs * 100) if total_runs > 0 else 0

        # Calculate accuracy metrics
        correct_moves_list = [s.correct_moves for s in stats if s.correct_moves is not None]
        wrong_moves_list = [s.wrong_moves for s in stats if s.wrong_moves is not None]
        scores = [s.score for s in stats if s.score is not None]
        times = [s.time_elapsed for s in stats if s.time_elapsed is not None]

        # Total moves for accuracy
        total_correct = sum(correct_moves_list)
        total_wrong = sum(wrong_moves_list)
        overall_accuracy = calculate_accuracy_rate(total_correct, total_wrong)

        # Calculate per-game accuracy for learning curve
        accuracy_per_game = []
        for i in range(len(stats)):
            if correct_moves_list[i] is not None and wrong_moves_list[i] is not None:
                game_accuracy = calculate_accuracy_rate(correct_moves_list[i], wrong_moves_list[i])
                accuracy_per_game.append(game_accuracy)

        # Decision time
        total_time = sum(times) if times else 0
        avg_decision_time = calculate_decision_time(total_time, total_correct, total_wrong)

        # Weighted average score (recent games weighted more)
        weighted_avg_score = calculate_weighted_metric(scores, use_recency_weight=True)

        # Improvement rate (compare first 5 to last 5 games)
        improvement_rate = 0
        if len(accuracy_per_game) >= 10:
            initial_avg = sum(accuracy_per_game[:5]) / 5
            recent_avg = sum(accuracy_per_game[-5:]) / 5
            if initial_avg > 0:
                improvement_rate = ((recent_avg - initial_avg) / initial_avg) * 100

        # Consistency score
        consistency = calculate_consistency_score(scores) if scores else 0

        # Learning curve analysis (overall)
        learning_curve_slope = 0
        learning_curve_trend = 'insufficient_data'
        if len(accuracy_per_game) >= 7:
            learning_curve_slope, learning_curve_trend = calculate_learning_curve_slope(accuracy_per_game)

        # Per-level learning curves
        level_performance = defaultdict(lambda: {
            'attempts': [],
            'accuracy_values': [],
            'score_values': [],
            'time_values': [],
            'learning_curve_slope': 0,
            'learning_curve_trend': 'insufficient_data'
        })

        # Group stats by level
        for i, stat in enumerate(stats):
            if stat.level is not None:
                level = stat.level
                level_performance[level]['attempts'].append(len(level_performance[level]['attempts']) + 1)

                # Calculate per-game metrics for this level
                if i < len(accuracy_per_game):
                    level_performance[level]['accuracy_values'].append(accuracy_per_game[i])
                if i < len(scores):
                    level_performance[level]['score_values'].append(scores[i])
                if i < len(times):
                    level_performance[level]['time_values'].append(times[i])

        # Calculate learning curves for each level
        for level, data in level_performance.items():
            if len(data['accuracy_values']) >= 7:
                slope, trend = calculate_learning_curve_slope(data['accuracy_values'])
                data['learning_curve_slope'] = slope
                data['learning_curve_trend'] = trend

        # Convert to regular dict for JSON serialization
        level_performance = dict(level_performance)

        # Check if student needs attention
        wrong_move_ratio = (total_wrong / (total_correct + total_wrong)) if (total_correct + total_wrong) > 0 else 0

        needs_attention = False
        attention_reason = []
        if learning_curve_trend == 'declining':
            needs_attention = True
            attention_reason.append('Declining performance')
        if wrong_move_ratio > 0.5:
            needs_attention = True
            attention_reason.append(f'High error rate ({wrong_move_ratio*100:.1f}% wrong moves)')

        # Check if student ready for rewards
        ready_for_reward = False
        reward_reason = []
        if learning_curve_trend == 'improving' and learning_curve_slope > 0.1:
            ready_for_reward = True
            reward_reason.append('Strong improvement')
        if overall_accuracy >= 90:
            ready_for_reward = True
            reward_reason.append('Exceptional accuracy')
        if consistency > 0.85 and weighted_avg_score > 0:  # Consistent high performer
            ready_for_reward = True
            reward_reason.append('Consistent excellence')

        student_info = {
            'id': student.id,
            'name': student.full_name,
            'classroom': student.classroom.classroom_name,
            'classroom_id': student.classroom.id,
            'classroom_key': student.classroom.classroom_key,
            'grade': student.grade,

            # Basic stats
            'total_runs': total_runs,
            'wins': wins,
            'win_rate': win_rate,

            # Enhanced metrics
            'accuracy': overall_accuracy,
            'avg_score': weighted_avg_score,
            'avg_decision_time': avg_decision_time,
            'improvement_rate': improvement_rate,
            'consistency': consistency,

            # Learning curve (overall)
            'learning_curve_slope': learning_curve_slope,
            'learning_curve_trend': learning_curve_trend,

            # Per-level performance (Phase 2)
            'level_performance': level_performance,

            # Raw data for charts
            'levels': [s.level for s in stats],
            'scores': scores,
            'times': times,
            'correct_moves': correct_moves_list,
            'wrong_moves': wrong_moves_list,
            'places': [s.place for s in stats],
            'accuracy_per_game': accuracy_per_game,

            # Flags
            'needs_attention': needs_attention,
            'attention_reason': ', '.join(attention_reason),
            'ready_for_reward': ready_for_reward,
            'reward_reason': ', '.join(reward_reason),
        }

        student_data.append(student_info)

        if needs_attention:
            students_needing_attention.append(student_info)
        if ready_for_reward:
            students_ready_for_rewards.append(student_info)

    # Sort students for top/bottom rankings
    top_by_accuracy = sorted([s for s in student_data], key=lambda x: x['accuracy'], reverse=True)[:10]
    top_by_improvement = sorted([s for s in student_data if s['improvement_rate'] != 0], key=lambda x: x['improvement_rate'], reverse=True)[:10]

    bottom_by_accuracy = sorted([s for s in student_data], key=lambda x: x['accuracy'])[:10]
    bottom_by_learning_curve = [s for s in student_data if s['learning_curve_trend'] in ['declining', 'plateaued'] and s['accuracy'] < 80]
    bottom_by_learning_curve = sorted(bottom_by_learning_curve, key=lambda x: x['learning_curve_slope'])[:10]

    # Prepare classroom-level statistics
    classroom_stats = []
    for classroom in classrooms:
        classroom_students = classroom.students.all()
        if grade_filter:
            classroom_students = classroom_students.filter(grade=grade_filter)

        all_runs = RunStatistics.objects.filter(student__in=classroom_students)

        if all_runs.exists():
            student_count = classroom_students.count()

            # Calculate classroom-wide accuracy
            total_correct = sum([r.correct_moves for r in all_runs if r.correct_moves is not None])
            total_wrong = sum([r.wrong_moves for r in all_runs if r.wrong_moves is not None])
            classroom_accuracy = calculate_accuracy_rate(total_correct, total_wrong)

            # Calculate average decision speed
            total_time = sum([r.time_elapsed for r in all_runs if r.time_elapsed is not None])
            avg_decision_time = calculate_decision_time(total_time, total_correct, total_wrong)

            # Engagement (games per student)
            engagement = all_runs.count() / student_count if student_count > 0 else 0

            classroom_info = {
                'id': classroom.id,
                'name': classroom.classroom_name,
                'key': classroom.classroom_key,
                'grade': classroom.grade,
                'student_count': student_count,
                'total_runs': all_runs.count(),
                'avg_score': all_runs.aggregate(Avg('score'))['score__avg'] or 0,
                'win_rate': (all_runs.filter(player_won=True).count() / all_runs.count() * 100) if all_runs.count() > 0 else 0,
                'accuracy': classroom_accuracy,
                'avg_decision_time': avg_decision_time,
                'engagement': engagement,
            }
            classroom_stats.append(classroom_info)

    # Get unique grades for filter
    all_grades = Student.objects.filter(classroom__teacher=teacher).values_list('grade', flat=True).distinct().order_by('grade')
    classroom_list = Classroom.objects.filter(teacher=teacher).order_by('classroom_name')

    context = {
        'teacher': teacher,
        'student_data': student_data,
        'student_data_json': json.dumps(student_data, default=str),
        'classroom_stats': classroom_stats,
        'classroom_stats_json': json.dumps(classroom_stats, default=str),

        # Enhanced panels
        'top_by_accuracy': top_by_accuracy,
        'top_by_improvement': top_by_improvement,
        'bottom_by_accuracy': bottom_by_accuracy,
        'bottom_by_learning_curve': bottom_by_learning_curve,
        'students_needing_attention': students_needing_attention,
        'students_ready_for_rewards': students_ready_for_rewards,

        # Filters
        'all_grades': all_grades,
        'classroom_list': classroom_list,
        'selected_grade': grade_filter,
        'selected_classroom': classroom_filter,

        # Enabled visualizations
        'enabled_viz': ENABLED_VISUALIZATIONS,
    }

    return render(request, 'digitmileapi/teacher_statistics.html', context)