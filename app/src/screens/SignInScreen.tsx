import { SignIn } from '@clerk/clerk-react';

export const SignInScreen = () => {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <h2 className="text-center text-3xl font-extrabold text-gray-900">
          LyncPower
        </h2>
        <p className="mt-2 text-center text-sm text-gray-600">
          Sign in to access charging stations
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <SignIn
          routing="virtual"
          fallbackRedirectUrl="/"
        />
      </div>
    </div>
  );
};
