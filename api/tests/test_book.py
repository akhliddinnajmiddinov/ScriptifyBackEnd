from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.urls import reverse
from apps.book.models import Book, BookReading
from django.contrib.auth import get_user_model
from oauth2_provider.models import Application
from django.core.files.uploadedfile import SimpleUploadedFile
from datetime import date
from apps.book.utils import generate_test_image
import json
import time

class BookAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(phone_number="+998940653474", password='test')
        self.user2 = get_user_model().objects.create_user(phone_number="+998883707279", password='test2')
        
        # Creating an OAuth2 application
        self.client_secret = "secret"
        self.application = Application.objects.create(
            name="Test Application",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_PASSWORD,
            client_secret=self.client_secret
            )
        
        # Authenticating using OAuth2
        response = self.client.post(
            reverse("oauth2_provider:token"),
            data={
                "grant_type": "password",
                "username": self.user.phone_number,
                "password": "test",
                "client_id": self.application.client_id,
                "client_secret": self.client_secret
            }
        )
        response_data = json.loads(response.content)
        self.token = response_data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        self.book1 = Book.objects.create(
            name="Book One",
            author="Author One",
            num_pages=300,
            pages_read=150,
            user=self.user
        )

        self.book2 = Book.objects.create(
            name="Book Two",
            author="Author Two",
            num_pages=400,
            pages_read=200,
            user=self.user
        )

        self.book3 = Book.objects.create(
            name="Book Two",
            author="Author Two",
            num_pages=400,
            pages_read=200,
            user=self.user
        )

        self.book4 = Book.objects.create(
            name="Book Two",
            author="Author Two",
            num_pages=400,
            pages_read=200,
            user=self.user2
        )

        self.list_url = reverse("book")
        self.object_one_url = "book_one"

    def test_get(self):
        response = self.client.get(reverse(self.object_one_url, kwargs={"pk": self.book1.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["data"], dict)
        self.assertEqual(response.data["data"]["id"], self.book1.id)
        print("Book GET: Success")

    def test_list(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["data"], list)
        book_ids = [book['id'] for book in response.data["data"]]
        self.assertIn(self.book1.id, book_ids)
        self.assertIn(self.book2.id, book_ids)
        self.assertIn(self.book3.id, book_ids)
        self.assertNotIn(self.book4.id, book_ids)
        print("Book LIST: Success")

    def test_list_with_limit_page1(self):
        response = self.client.get(self.list_url, data={"limit": 2, "page": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"]["data"], list)
        book_ids = [book['id'] for book in response.data["results"]["data"]]
        self.assertIn(self.book2.id, book_ids)
        self.assertIn(self.book3.id, book_ids)
        self.assertNotIn(self.book1.id, book_ids)
        self.assertNotIn(self.book4.id, book_ids)
        print("Book LIST with limit and page 1: Success")

    def test_list_with_limit_page2(self):
        response = self.client.get(self.list_url, data={"limit": 2, "page": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"]["data"], list)
        book_ids = [book['id'] for book in response.data["results"]["data"]]
        self.assertIn(self.book1.id, book_ids)
        self.assertNotIn(self.book2.id, book_ids)
        self.assertNotIn(self.book3.id, book_ids)
        self.assertNotIn(self.book4.id, book_ids)
        print("Book LIST with limit and page 2: Success")

    def test_post(self):
        image = generate_test_image()

        data = {
            "name": "Book Three",
            "author": "Author Three",
            "num_pages": 500,
            "pages_read": 250,
            "user": self.user.id,
            "image": image
        }
        response = self.client.post(self.list_url, data=data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Book Three")
        print("Book POST: Success")

    def test_put(self):
        data = {
            "name": "Updated Book One",
            "num_pages": 350
        }
        response = self.client.put(reverse(self.object_one_url, kwargs={"pk": self.book1.id}), data=json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "Updated Book One")
        self.assertEqual(response.data["data"]["num_pages"], 350)
        print("Book PUT: Success")

    def test_delete(self):
        response = self.client.delete(reverse(self.object_one_url, kwargs={"pk": self.book2.id}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Book.objects.filter(id=self.book1.id).exists())
        self.assertTrue(Book.objects.filter(id=self.book3.id).exists())
        self.assertTrue(Book.objects.filter(id=self.book4.id).exists())
        self.assertFalse(Book.objects.filter(id=self.book2.id).exists())
        print("Book DELETE: Success")


class BookReadingAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(phone_number="+998940653474", password='test')
        self.user2 = get_user_model().objects.create_user(phone_number="+998883707279", password='test2')
        
        # Creating an OAuth2 application
        self.client_secret = "secret"
        self.application = Application.objects.create(
            name="Test Application",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_PASSWORD,
            client_secret=self.client_secret
            )

        self.authenticate(self.user.phone_number, "test")
        
        self.book1 = Book.objects.create(
            name="Book One",
            author="Author One",
            num_pages=300,
            pages_read=150,
            user=self.user
        )

        self.book2 = Book.objects.create(
            name="Book Two",
            author="Author Two",
            num_pages=400,
            pages_read=200,
            user=self.user
        )

        self.book4 = Book.objects.create(
            name="Book Four",
            author="Author Two",
            num_pages=400,
            pages_read=200,
            user=self.user2
        )

        self.book_reading1 = BookReading.objects.create(
            book=self.book1,
            time_read=10,
            end_page=160
        )


        self.book_reading2 = BookReading.objects.create(
            book=self.book1,
            time_read=10,
            end_page=170
        )

        self.book_reading3 = BookReading.objects.create(
            book=self.book1,
            time_read=10,
            end_page=180
        )

        self.book_reading4 = BookReading.objects.create(
            book=self.book2,
            time_read=10,
            end_page=210
        )

        self.book_reading5 = BookReading.objects.create(
            book=self.book2,
            time_read=10,
            end_page=220
        )

        self.book_reading6 = BookReading.objects.create(
            book=self.book4,
            time_read=10,
            end_page=210
        )

        self.book_reading7 = BookReading.objects.create(
            book=self.book4,
            time_read=10,
            end_page=220
        )

        self.list_url = reverse("book_reading")
        self.list_by_book = "book_reading_by_book"
        self.object_one_url = "book_reading_one"

    def authenticate(self, username: str, password: str) -> None:
        # Authenticating using OAuth2
        response = self.client.post(
            reverse("oauth2_provider:token"),
            data={
                "grant_type": "password",
                "username": username,
                "password": password,
                "client_id": self.application.client_id,
                "client_secret": self.client_secret
            }
        )
        response_data = json.loads(response.content)
        self.token = response_data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")


    def test_get(self):
        response = self.client.get(reverse(self.object_one_url, kwargs={"pk": self.book_reading1.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["data"], dict)
        self.assertEqual(response.data["data"]["id"], self.book_reading1.id)
        self.assertEqual(response.data["data"]["book_data"]["id"], self.book1.id)
        self.assertEqual(response.data["data"]["end_page"], self.book_reading1.end_page)
        self.assertEqual(response.data["data"]["time_read"], self.book_reading1.time_read)
        print("BookReading GET: Success")

    def test_list(self):
        response = self.client.get(self.list_url)
        print(response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["data"], list)
        item_ids = [item['id'] for item in response.data["data"]]
        self.assertIn(self.book_reading1.id, item_ids)
        self.assertIn(self.book_reading2.id, item_ids)
        self.assertIn(self.book_reading3.id, item_ids)
        self.assertIn(self.book_reading4.id, item_ids)
        self.assertIn(self.book_reading5.id, item_ids)
        self.assertNotIn(self.book_reading6.id, item_ids)
        self.assertNotIn(self.book_reading7.id, item_ids)
        print("BookReading LIST: Success")

    def test_list_with_limit_page1(self):
        response = self.client.get(self.list_url, data={"limit": 3, "page": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"]["data"], list)
        item_ids = [item['id'] for item in response.data["results"]["data"]]
        self.assertNotIn(self.book_reading1.id, item_ids)
        self.assertNotIn(self.book_reading2.id, item_ids)
        self.assertIn(self.book_reading3.id, item_ids)
        self.assertIn(self.book_reading4.id, item_ids)
        self.assertIn(self.book_reading5.id, item_ids)
        self.assertNotIn(self.book_reading6.id, item_ids)
        self.assertNotIn(self.book_reading7.id, item_ids)
        print("BookReading LIST with limit and page 1: Success")

    def test_list_with_limit_page2(self):
        response = self.client.get(self.list_url, data={"limit": 3, "page": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"]["data"], list)
        item_ids = [item['id'] for item in response.data["results"]["data"]]
        self.assertIn(self.book_reading1.id, item_ids)
        self.assertIn(self.book_reading2.id, item_ids)
        self.assertNotIn(self.book_reading3.id, item_ids)
        self.assertNotIn(self.book_reading4.id, item_ids)
        self.assertNotIn(self.book_reading5.id, item_ids)
        self.assertNotIn(self.book_reading6.id, item_ids)
        self.assertNotIn(self.book_reading7.id, item_ids)
        print("BookReading LIST with limit and page 1: Success")

    def test_list_with_invalid_page(self):
        response = self.client.get(self.list_url, data={"limit": 3, "page": 3})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(self.list_url, data={"limit": 3, "page": 0})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        print("BookReading LIST with limit and page 1: Success")

    def test_list_with_book_id(self):
        response = self.client.get(self.list_url, data={"limit": 3, "page": 1, "book_id": self.book2.id})
        print(response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data["results"]["data"], list)
        item_ids = [item['id'] for item in response.data["results"]["data"]]
        self.assertIn(self.book_reading4.id, item_ids)
        self.assertIn(self.book_reading5.id, item_ids)
        self.assertNotIn(self.book_reading1.id, item_ids)
        self.assertNotIn(self.book_reading2.id, item_ids)
        self.assertNotIn(self.book_reading3.id, item_ids)
        self.assertNotIn(self.book_reading6.id, item_ids)
        self.assertNotIn(self.book_reading7.id, item_ids)
        print("BookReading LIST with book_id: Success")


    def test_post(self):
        data = {
            "book": self.book1.id,
            "time_read": 10,
            "end_page": 250
        }
        response = self.client.post(self.list_url, data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["book_data"]['id'], self.book1.id)
        self.assertEqual(response.data["data"]["time_read"], data["time_read"])
        self.assertEqual(response.data["data"]["end_page"], data["end_page"])
        self.book1.refresh_from_db()
        self.assertEqual(self.book1.pages_read, data["end_page"])
        print("BookReading POST: Success")

    def test_post_with_invalid_end_page(self):
        # with lower end_page from book.pages_read
        data = {
            "book": self.book1.id,
            "time_read": 10,
            "end_page": 100
        }
        response = self.client.post(self.list_url, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # with higher end_page than book.num_pages

        data = {
            "book": self.book1.id,
            "time_read": 10,
            "end_page": 350
        }
        response = self.client.post(self.list_url, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        print("BookReading POST with invalid end page: Success")

    def test_delete(self):
        response = self.client.delete(reverse(self.object_one_url, kwargs={"pk": self.book_reading3.id}))
        print(response.data)
        self.book1.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.book1.pages_read, self.book_reading2.end_page)
        self.assertTrue(BookReading.objects.filter(id=self.book_reading1.id).exists())
        self.assertTrue(BookReading.objects.filter(id=self.book_reading2.id).exists())
        self.assertFalse(BookReading.objects.filter(id=self.book_reading3.id).exists())
        self.assertTrue(BookReading.objects.filter(id=self.book_reading4.id).exists())
        self.assertTrue(BookReading.objects.filter(id=self.book_reading5.id).exists())
        self.assertTrue(BookReading.objects.filter(id=self.book_reading6.id).exists())
        self.assertTrue(BookReading.objects.filter(id=self.book_reading7.id).exists())
        print("BookReading DELETE: Success")
    
    def test_delete_with_not_last_book_reading(self):
        response = self.client.delete(reverse(self.object_one_url, kwargs={"pk": self.book_reading2.id}))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        print("BookReading DELETE with not last BookReading: Success")