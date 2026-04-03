"""Hotel search implementation.

This module provides hotel search functionality by wrapping the fast_hotels
library, which interfaces with Google Travel's hotel search.
"""

from __future__ import annotations

from dataclasses import dataclass

from fast_hotels import get_hotels
from fast_hotels.hotels_impl import Guests as FastHotelGuests
from fast_hotels.hotels_impl import HotelData as FastHotelData


@dataclass
class HotelResult:
    """A single hotel search result."""

    name: str
    price: float
    rating: float | None = None
    url: str | None = None
    amenities: list[str] | None = None


class SearchHotels:
    """Hotel search implementation using Google Travel.

    This class handles searching for hotels at a given location,
    parsing the results into structured data models.
    """

    def search(
        self,
        location: str,
        check_in_date: str,
        check_out_date: str,
        adults: int = 2,
        children: int = 0,
        currency: str = "USD",
        sort_by: str | None = None,
        limit: int | None = None,
    ) -> list[HotelResult] | None:
        """Search for hotels using Google Travel.

        Args:
            location: City name or IATA airport code
            check_in_date: Check-in date (YYYY-MM-DD)
            check_out_date: Check-out date (YYYY-MM-DD)
            adults: Number of adult guests
            children: Number of child guests
            currency: Currency code (e.g., USD, EUR)
            sort_by: Sort results by 'price', 'rating', or None for best value
            limit: Maximum number of results to return

        Returns:
            List of HotelResult objects, or None if no results found

        Raises:
            Exception: If the search fails

        """
        try:
            hotel_data = [
                FastHotelData(
                    checkin_date=check_in_date,
                    checkout_date=check_out_date,
                    location=location,
                )
            ]

            guests = FastHotelGuests(adults=adults, children=children)

            result = get_hotels(
                hotel_data=hotel_data,
                guests=guests,
                sort_by=sort_by,
                limit=limit,
            )

            if not result or not result.hotels:
                return None

            return [
                HotelResult(
                    name=h.name,
                    price=h.price,
                    rating=h.rating,
                    url=h.url,
                    amenities=h.amenities or [],
                )
                for h in result.hotels
            ]

        except Exception as e:
            raise Exception(f"Hotel search failed: {str(e)}") from e
