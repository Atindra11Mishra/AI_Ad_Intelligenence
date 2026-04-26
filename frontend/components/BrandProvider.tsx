"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { apiFetch } from "@/lib/api";
import { Brand } from "@/lib/types";

type BrandContextType = {
  brands: Brand[];
  selectedBrandId: number | null;
  selectedBrand: Brand | null;
  loadingBrands: boolean;
  refreshBrands: () => Promise<void>;
  setSelectedBrandId: (id: number | null) => void;
};

const BrandContext = createContext<BrandContextType | undefined>(undefined);

export function BrandProvider({ children }: { children: ReactNode }) {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedBrandId, setSelectedBrandIdState] = useState<number | null>(
    null
  );
  const [loadingBrands, setLoadingBrands] = useState(false);

  const selectedBrand =
    brands.find((brand) => brand.id === selectedBrandId) || null;

  async function refreshBrands() {
    setLoadingBrands(true);

    try {
      const data = await apiFetch<Brand[]>("/brands");
      setBrands(data);

      const storedId = localStorage.getItem("selectedBrandId");

      if (storedId && data.some((brand) => brand.id === Number(storedId))) {
        setSelectedBrandIdState(Number(storedId));
      } else if (data.length > 0 && selectedBrandId === null) {
        setSelectedBrandIdState(data[0].id);
        localStorage.setItem("selectedBrandId", String(data[0].id));
      }
    } finally {
      setLoadingBrands(false);
    }
  }

  function setSelectedBrandId(id: number | null) {
    setSelectedBrandIdState(id);

    if (id) {
      localStorage.setItem("selectedBrandId", String(id));
    } else {
      localStorage.removeItem("selectedBrandId");
    }
  }

  useEffect(() => {
    void Promise.resolve().then(refreshBrands);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <BrandContext.Provider
      value={{
        brands,
        selectedBrandId,
        selectedBrand,
        loadingBrands,
        refreshBrands,
        setSelectedBrandId,
      }}
    >
      {children}
    </BrandContext.Provider>
  );
}

export function useBrand() {
  const context = useContext(BrandContext);

  if (!context) {
    throw new Error("useBrand must be used inside BrandProvider");
  }

  return context;
}
